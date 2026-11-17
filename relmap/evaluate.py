"""Run the prompt conditions on a model and report results.

    python -m relmap.evaluate check   --model <name> --base-url <server>/v1     # try a new model first
    python -m relmap.evaluate run     --model <name> --base-url <server>/v1 --split dev
    python -m relmap.evaluate report  results/<name>.jsonl
    python -m relmap.evaluate rescore results/<name>.jsonl   # re-parse stored replies after a parser change

Works with any server that speaks the OpenAI chat-completions format (LM Studio,
llama.cpp, vLLM, Google AI Studio, ...). If the server needs a key, set the
environment variable RELMAP_API_KEY. `--model mock` runs offline for testing.

Conditions (one model call each, same question, same relation-type list):
  direct   answer straight away
  cot      generic step-by-step reasoning, then answer
  restate  restate each story in its own words, then answer   (control: re-reading without structure)
  extract  list every relationship as (head, TYPE, tail), then answer   -> "extract_llm"
           the same triples matched by code instead of the model        -> "extract_code"
  extract_compare  list the triples, compare each candidate's list to the source, then answer
  gold     the true triples are given instead of the stories            -> "gold_llm"
  map      pair each source character with one character in every candidate, then answer
                                                                         -> "map_llm"
           code checks which candidate the model's own pairings fit     -> "map_code"
  direct_shuf, gold_shuf
           direct and gold with the candidates moved two places (A->C, B->D, ...)
                                                                         -> "direct_shuf", "gold_llm_shuf"
Derived in the report, no model calls:
  hybrid   extract_code's answer when code finds exactly one match, otherwise cot's answer

cot, restate and extract share one free-text output format and one token cap, so
they differ only in what the model is asked to write before answering.

Question 3 (is listing special): extract_llm vs cot, and extract_llm vs restate.
Question 1 (reading vs matching): extract_code vs gold_llm.
Role binding: map_llm, and how often its pairing for the true match is right.
Position: does the model pick the same story, or the same letter, when the order changes?
"""

import argparse
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from . import graphs
from .realize import parse
from .schema import DOMAINS, RELATIONS
from .verify import load, to_graph

LETTERS = "ABCD"
RULE = ("Two stories are analogous when their entities can be paired one-to-one so that every "
        "relationship in one story corresponds to a relationship of the same type and the same "
        "direction in the other. Names, settings and wording do not matter.")
TYPES = "Relationship types:\n" + "\n".join(f"- {k}: {v}" for k, v in RELATIONS.items())
FINAL = "end with a final line in exactly this form: Answer: <letter>"
ENDINGS = {
    "direct": "Do not explain or restate anything. Reply with only this line: Answer: <letter>",
    "cot": f"Think step by step, then {FINAL}",
    "restate": ("First restate the source story and each candidate story in your own words, under the "
                f"headings Source, A, B, C and D. Then {FINAL}"),
    "extract": ("First list every relationship in the source story and in each candidate story, one per "
                "line as (head, TYPE, tail) using the relationship types above, under the headings "
                f"Source, A, B, C and D. Then {FINAL}"),
    "extract_compare": ("First list every relationship in the source story and in each candidate story, one per "
                        "line as (head, TYPE, tail) using the relationship types above, under the headings "
                        "Source, A, B, C and D. Then, under the heading Comparison, check each candidate's "
                        f"list against the source list. Then {FINAL}"),
    "cot_brief": f"Reason briefly, in at most 150 words, then {FINAL}",
    "gold_cot": f"Think step by step, then {FINAL}",
    "gold": "Do not explain or restate anything. Reply with only this line: Answer: <letter>",
    "map": ("First, for each candidate story, pair every character in the source story with the character "
            "in that candidate who plays the same role, one pair per line as <source name> = <candidate name>, "
            f"under the headings A, B, C and D. Then {FINAL}"),
}
ENDINGS["direct_shuf"] = ENDINGS["direct"]
ENDINGS["gold_shuf"] = ENDINGS["gold"]
REASONING_CAP = 3000  # same output budget for every condition that writes before answering
RESULT_NAME = {"gold": "gold_llm", "extract": "extract_llm", "map": "map_llm", "gold_shuf": "gold_llm_shuf"}
ORDER = ["direct", "cot", "cot_brief", "restate", "extract_llm", "extract_compare", "extract_code",
         "hybrid", "map_llm", "map_code", "gold_llm", "gold_cot", "direct_shuf", "gold_llm_shuf"]
SHIFT = 2  # how far the _shuf conditions move every candidate


def shuffled(q):
    """The same question with every candidate moved SHIFT places, letters reassigned."""
    cands = q["candidates"][-SHIFT:] + q["candidates"][:-SHIFT]
    cands = [{**c, "label": letter} for c, letter in zip(cands, LETTERS)]
    answer = next(c["label"] for c in cands if c["role"] == "true_match")
    return {**q, "candidates": cands, "answer": answer}


def prompt(q, cond):
    if cond.startswith("gold"):
        show = lambda s: "; ".join(f"({h}, {r}, {t})" for h, r, t in s["triples"])
        head = "Source relationships"
    else:
        show = lambda s: s["text"]
        head = "Source story"
    cands = "\n".join(f"{c['label']}. {show(c)}" for c in q["candidates"])
    return (f"{RULE}\n\n{TYPES}\n\n{head}:\n{show(q['source'])}\n\nCandidates:\n{cands}\n\n"
            f"Exactly one candidate is analogous to the source. {ENDINGS[cond]}")


# ---------- model clients ----------

ANSWER_ONLY = {"direct", "gold", "direct_shuf", "gold_shuf"}


def cap_for(cond, opts):
    """Output-token cap: short for answer-only prompts, long for everything that writes first."""
    return opts.answer_cap if cond in ANSWER_ONLY else opts.reasoning_cap


def prompt_id(cond):
    """Short fingerprint of a condition's full prompt template, stored with every row,
    so results from different prompt wordings are never mixed without notice."""
    import hashlib
    return hashlib.sha1(f"{RULE}|{TYPES}|{ENDINGS[cond]}|{SHIFT if cond.endswith('_shuf') else ''}".encode()).hexdigest()[:8]


def call_openai(base_url, model, text, max_tokens, opts):
    """One chat-completions request. Returns (reply text, output tokens, finish reason, had_hidden_thinking)."""
    body = {"model": model, "messages": [{"role": "user", "content": text}], opts.token_param: max_tokens}
    if opts.temperature is not None:
        body["temperature"] = opts.temperature
    body.update(opts.extra_body)
    headers = {"Content-Type": "application/json"}
    if os.environ.get("RELMAP_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["RELMAP_API_KEY"]
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                 json.dumps(body).encode(), headers)
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                out = json.load(r)
            break
        except urllib.error.HTTPError as e:
            # Rate limit or server hiccup: wait and retry. Anything else is a real error.
            if e.code not in (429, 500, 502, 503) or attempt == 7:
                raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
            time.sleep(min(60, 5 * 2 ** attempt))
    choice = out["choices"][0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    if isinstance(content, list):  # some servers return a list of content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    hidden = bool(msg.get("reasoning_content") or msg.get("reasoning"))
    return content, (out.get("usage") or {}).get("completion_tokens"), choice.get("finish_reason"), hidden


THINK = re.compile(r"<(think|thinking|reasoning)>.*?(</\1>|\Z)", re.S | re.I)
HARMONY_FINAL = re.compile(r"<\|channel\|>\s*final\s*<\|message\|>(.*)", re.S)


def strip_thinking(text):
    """Remove reasoning that some models print inside the reply (<think>...</think>, or the
    analysis channel of harmony-format models), so parsers only see the final answer."""
    m = HARMONY_FINAL.search(text)
    if m:
        text = m.group(1)
    return THINK.sub("", text).strip()


def call_mock(q, cond, rng):
    """Offline stand-in: reads perfectly, guesses when it has to match by itself."""
    guess = f"Answer: {rng.choice(LETTERS)}"
    if cond == "map":
        # Correct pairing for the true match, an arbitrary one for the others.
        blocks = []
        for c in q["candidates"]:
            m = q["gold_mappings"][0] if c["label"] == q["answer"] else dict(zip(q["source"]["entities"], c["entities"]))
            blocks.append(f"{c['label']}:\n" + "\n".join(f"{s} = {t}" for s, t in m.items()))
        return "\n\n".join(blocks) + f"\n\n{guess}", None, "stop"
    if cond != "extract":
        return guess, None, "stop"
    stories = [("Source", q["source"])] + [(c["label"], c) for c in q["candidates"]]
    blocks = [f"{tag}:\n" + "\n".join(f"({h}, {r}, {t})" for h, r, t in parse(s["domain"], s["text"]))
              for tag, s in stories]
    return "\n\n".join(blocks) + f"\n\n{guess}", None, "stop"


# ---------- parsing and scoring ----------

# "Answer: C", "**Answer:** (C)", "ANSWER - C", "The answer is C", "Final answer: Candidate C".
# The word "answer" may be any case; the letter must be a capital A-D standing on its own.
ANSWER = re.compile(r"(?i:\banswer)\b[^\w\n]{0,12}(?:(?i:is|would be|should be|:)[^\w\n]{0,6})?"
                    r"(?:(?i:candidate|option|story)\s+)?\(?([ABCD])(?![\w'])")
BARE_LETTER = re.compile(r"^[^\w]*([ABCD])[^\w]*$")


def parse_letter(text):
    """The last stated answer letter, or None. A reply that is only a letter also counts."""
    hits = ANSWER.findall(text)
    if hits:
        return hits[-1]
    m = BARE_LETTER.match(text.strip())
    return m.group(1) if m else None


HEADING = re.compile(r"\W*(?:(source)(?:\s+story)?|(?:candidate\s+)?([A-D]))\b(?!\s*,)", re.I)
TRIPLE = re.compile(r"[(\[]\s*['\"]?(\w+)['\"]?\s*,\s*['\"]?(\w+)['\"]?\s*,\s*['\"]?(\w+)['\"]?\s*[)\]]")


def parse_extraction(text):
    """Read '(head, TYPE, tail)' lines grouped under Source / A / B / C / D headings."""
    stories = {k: [] for k in ("source", *LETTERS)}
    current = None
    for line in text.splitlines():
        if re.match(r"\W*Answer", line):
            break
        m = HEADING.match(line)
        if m:
            current = "source" if m.group(1) else m.group(2).upper()
        if current:
            stories[current] += [[h, r.upper(), t] for h, r, t in TRIPLE.findall(line)]
    return stories if stories["source"] else None


def score_extraction(q, stories):
    """Triple precision/recall counts and a breakdown of what went wrong."""
    gold = {"source": q["source"], **{c["label"]: c for c in q["candidates"]}}
    tp = n_pred = n_gold = n_perfect = 0
    errors, forms = Counter(), Counter()
    for key, story in gold.items():
        g = {tuple(t) for t in story["triples"]}
        p = {tuple(t) for t in stories[key]}
        for h, r, t in g:
            # Third template of each relation is the passive-style one (tail mentioned first).
            passive = DOMAINS[story["domain"]]["lex"][r][2].format(x=h, y=t) in story["text"]
            kind = "passive" if passive else "active"
            forms[kind + "_n"] += 1
            forms[kind + "_missed"] += (h, r, t) not in p
            forms[kind + "_reversed"] += (h, r, t) not in p and (t, r, h) in p
        tp, n_pred, n_gold = tp + len(g & p), n_pred + len(p), n_gold + len(g)
        n_perfect += g == p
        for h, r, t in g - p:
            if (t, r, h) in p:
                errors["direction"] += 1
            elif any({ph, pt} == {h, t} for ph, _, pt in p):
                errors["type"] += 1
            else:
                errors["missing"] += 1
    return {"tp": tp, "n_pred": n_pred, "n_gold": n_gold, "errors": dict(errors), "forms": dict(forms),
            "all_correct": n_perfect == 5}


def code_match(stories):
    """Pick the candidate whose extracted graph matches the extracted source."""
    def g(key):
        triples = [list(t) for t in {tuple(t) for t in stories[key]}]
        return to_graph(triples) if triples else None
    src = g("source")
    hits = [k for k in LETTERS if g(k) and graphs.matches(src, g(k))]
    return (hits[0] if len(hits) == 1 else None), len(hits)


# Arrow or equals sign between two names, in the forms the model actually writes:
# "Rosa = Lila", "Rosa -> Lila", "Rosa → Lila", "Rosa $\rightarrow$ Lila", "Rosa maps to Lila".
ARROW = r"\s*(?:=|-+>|→|⟶|:|\$?\\(?:rightarrow|to|mapsto|longrightarrow)\$?|maps to|corresponds to|pairs with)\s*"
# A line that opens a candidate's block: "Candidate A analysis:", "**B:**", "C.", "### D".
# The letter must be upper case and followed by punctuation, the end, or a heading word,
# so a sentence that starts with the article "A" does not open a block.
HEAD_LINE = re.compile(r"\W*(?:(?i:candidate|option|story)\s+)?([A-D])\s*"
                       r"(?:[:.)*]|$|\s+(?i:analysis|story|mapping|pairs|pairing|roles)\b)")


def parse_mapping(text, q):
    """Pairs 'source name -> candidate name' grouped by candidate, using the known character names.

    A new block starts at a line that opens with a candidate letter ("Candidate A", "**B:**", "C.").
    Only names that really occur in the source and in that candidate are kept, so free-form
    replies are read as well as replies that follow the requested format."""
    src = q["source"]["entities"]
    cand_names = {c["label"]: c["entities"] for c in q["candidates"]}
    maps = {k: {} for k in LETTERS}
    current = None
    for line in text.splitlines():
        if re.match(r"\W*Answer\W*[ABCD]\b", line):
            break
        m = HEAD_LINE.match(line)
        if m and not any(line.lstrip(" *#-").startswith(n) for n in src):
            current = m.group(1).upper()
        if not current:
            continue
        names = "|".join(map(re.escape, cand_names[current]))
        for s in src:
            p = re.search(rf"\b{re.escape(s)}\b{ARROW}\W*({names})\b", line)
            if p:
                maps[current].setdefault(s, p.group(1))
    return maps if any(maps.values()) else None


def score_mapping(q, maps):
    """Is the pairing written for the true match right, and which candidates do the pairings fit?"""
    src = q["source"]
    true = maps.get(q["answer"], {})
    pairing_right = any(all(true.get(s) == g[s] for s in src["entities"]) for g in q["gold_mappings"])
    fits = []
    for c in q["candidates"]:
        m = maps.get(c["label"], {})
        mapped = {(m.get(h), r, m.get(t)) for h, r, t in src["triples"]}
        if mapped == {tuple(t) for t in c["triples"]}:
            fits.append(c["label"])
    return pairing_right, fits


def evaluate_question(q, cond, text):
    """Return result rows for one model response."""
    base = {"id": q["id"], "group": q["paraphrase_group"], "split": q["split"],
            "n_edges": q["n_edges"], "answer": q["answer"]}
    roles = {c["label"]: c["role"] for c in q["candidates"]}
    edits = {c["label"]: c["perturbation"] for c in q["candidates"]}

    def row(name, pred, **extra):
        return {**base, "condition": name, "pred": pred, "correct": pred == q["answer"],
                "picked_role": roles.get(pred), "picked_edit": edits.get(pred), **extra}

    rows = [row(RESULT_NAME.get(cond, cond), parse_letter(text))]
    if cond == "extract":
        stories = parse_extraction(text)
        if stories is None:
            rows.append(row("extract_code", None, parse_failed=True))
        else:
            rows[0]["extraction"] = score_extraction(q, stories)
            pred, n_hits = code_match(stories)
            rows.append(row("extract_code", pred, n_code_matches=n_hits))
    if cond == "map":
        maps = parse_mapping(text, q)
        if maps is None:
            rows[0]["mapping_right"] = None
            rows.append(row("map_code", None, parse_failed=True))
        else:
            right, fits = score_mapping(q, maps)
            rows[0]["mapping_right"] = right
            rows.append(row("map_code", fits[0] if len(fits) == 1 else None, n_code_matches=len(fits)))
    return rows


# ---------- run ----------

def run(args):
    qs = [q for q in load(args.data) if args.split in ("all", q["split"])]
    if args.limit:
        # Sample whole paraphrase groups so twins stay together.
        groups = sorted({q["paraphrase_group"] for q in qs})
        random.Random(0).shuffle(groups)
        keep, n = set(), 0
        for g in groups:
            if n >= args.limit:
                break
            keep.add(g)
            n += sum(q["paraphrase_group"] == g for q in qs)
        qs = [q for q in qs if q["paraphrase_group"] in keep]
    out = Path(args.out or f"results/{re.sub(r'[^\w.-]', '_', args.model)}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    old = load(out) if out.exists() else []
    done = {(r["id"], r["raw_condition"]) for r in old}
    conds = args.conditions.split(",")
    for cond in conds:
        stored = {r.get("prompt_id") for r in old if r["raw_condition"] == cond}
        if stored and stored != {prompt_id(cond)}:
            print(f"warning: {out} already holds '{cond}' rows from a different prompt wording "
                  f"({', '.join(sorted(str(s) for s in stored))}); those questions are skipped, not rerun. "
                  f"Use a new --out file to rerun with the current wording.")
    with out.open("a", encoding="utf-8") as f:
        for i, q in enumerate(qs, 1):
            for cond in conds:
                if (q["id"], cond) in done:
                    continue
                for r in ask(q, cond, args):
                    f.write(json.dumps(r) + "\n")
                f.flush()
            print(f"\r{i}/{len(qs)} questions", end="", flush=True)
    print(f"\nresults in {out}")
    report(out)


_mock_rng = random.Random(0)


def ask(q, cond, args):
    """Send one question under one condition; return its scored result rows."""
    qq = shuffled(q) if cond.endswith("_shuf") else q
    if args.model == "mock":
        raw, tokens, finish = call_mock(qq, cond, _mock_rng)
        hidden = False
    else:
        raw, tokens, finish, hidden = call_openai(args.base_url, args.model, prompt(qq, cond), cap_for(cond, args), args)
    text = strip_thinking(raw)
    meta = {"raw_condition": cond, "output_tokens": tokens, "output_words": len(text.split()),
            "cut_off": finish == "length", "empty_reply": not text.strip(), "response": text,
            "prompt_id": prompt_id(cond), "model": args.model,
            "settings": {"temperature": args.temperature, "cap": cap_for(cond, args),
                         "token_param": args.token_param, "extra_body": args.extra_body}}
    if raw != text:
        meta["thinking_removed"] = True
    if hidden:
        meta["hidden_thinking"] = True
    return [{**r, **meta} for r in evaluate_question(qq, cond, text)]


CHECK_CONDITIONS = ["direct", "gold", "cot", "extract", "map"]


def check(args):
    """Quick compatibility check on a few dev questions; writes nothing."""
    qs = [q for q in load(args.data) if q["split"] == "dev" and not q["is_paraphrase"]]
    qs = sorted(qs, key=lambda q: (q["n_edges"], q["id"]))[::max(1, len(qs) // args.n)][:args.n]
    print(f"checking {args.model} at {args.base_url} on {len(qs)} dev questions "
          f"({', '.join(str(q['n_edges']) for q in qs)} relationships)\n")
    print(f"{'condition':10s} {'answered':>8s} {'empty':>6s} {'cut off':>8s} {'thinking':>9s} {'lists read':>11s}")
    problems = []
    for cond in CHECK_CONDITIONS:
        rows = [ask(q, cond, args) for q in qs]
        first = [r[0] for r in rows]
        answered = sum(r["pred"] is not None for r in first)
        empty = sum(r["empty_reply"] for r in first)
        cut = sum(r["cut_off"] for r in first)
        think = sum(bool(r.get("thinking_removed") or r.get("hidden_thinking")) for r in first)
        lists = (f"{sum(len(r) > 1 and not r[1].get('parse_failed') for r in rows)}/{len(qs)}"
                 if cond in ("extract", "map") else "-")
        print(f"{cond:10s} {answered:5d}/{len(qs):<2d} {empty:6d} {cut:8d} {think:9d} {lists:>11s}")
        if empty and cond in ANSWER_ONLY:
            problems.append(f"{cond}: {empty} empty replies. The model probably spends its {args.answer_cap} "
                            "answer tokens on hidden thinking. Turn thinking off on the server (llama.cpp: "
                            "--reasoning off; vLLM/Qwen3: --extra-body '{\"chat_template_kwargs\": "
                            "{\"enable_thinking\": false}}') or raise --answer-cap.")
        elif answered < len(qs):
            miss = next(r for r in first if r["pred"] is None)
            problems.append(f"{cond}: {len(qs) - answered} replies with no readable answer. One reply ends: "
                            f"...{miss['response'][-200:]!r}")
        if cut and not (empty and cond in ANSWER_ONLY):  # empty answer-only replies are reported above
            flag = "--answer-cap" if cond in ANSWER_ONLY else "--reasoning-cap"
            problems.append(f"{cond}: {cut} replies hit the {cap_for(cond, args)}-token cap. Raise {flag} "
                            "if the server's context window allows it.")
    print()
    if problems:
        print("problems found:")
        for p in problems:
            print("  -", p)
    else:
        print("no problems found: replies are non-empty, finished, and readable by every parser.")


def rescore(path):
    """Re-parse every stored reply with the current parsers and rewrite the results file
    (a .bak copy is kept). Run after changing a parser so old and new results are scored alike."""
    path = Path(path)
    qs = {q["id"]: q for q in load("data/questions.jsonl")}
    rows = load(path)
    seen, out, changed = set(), [], Counter()
    old_pred = {(r["id"], r["condition"]): r["pred"] for r in rows}
    for r in rows:
        key = (r["id"], r["raw_condition"])
        if key in seen:
            continue
        seen.add(key)
        q = qs[r["id"]]
        qq = shuffled(q) if r["raw_condition"].endswith("_shuf") else q
        keep = {k: v for k, v in r.items() if k in (
            "raw_condition", "output_tokens", "output_words", "cut_off", "empty_reply", "response", "prompt_id",
            "model", "settings", "thinking_removed", "hidden_thinking")}
        for new in evaluate_question(qq, r["raw_condition"], r["response"]):
            changed[new["condition"]] += new["pred"] != old_pred.get((new["id"], new["condition"]))
            out.append({**new, **keep})
    path.with_suffix(".jsonl.bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    with path.open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    print(f"rescored {len(out)} rows in {path} (backup: {path.with_suffix('.jsonl.bak')})")
    print("answers that changed:", {k: v for k, v in changed.items() if v} or "none")


# ---------- report ----------

def ci(by_group, n=2000, seed=0):
    """Bootstrap 95% interval for a mean, resampling paraphrase groups (twins are not independent)."""
    rng = random.Random(seed)
    groups = list(by_group.values())
    means = []
    for _ in range(n):
        vals = [v for g in rng.choices(groups, k=len(groups)) for v in g]
        means.append(sum(vals) / len(vals))
    means.sort()
    return means[int(0.025 * n)], means[int(0.975 * n)]


def grouped(rows, value):
    out = defaultdict(list)
    for r in rows:
        out[r["group"]].append(value(r))
    return out


def report(path):
    rows = load(path)
    by = defaultdict(dict)
    for r in rows:
        by[r["condition"]][r["id"]] = r
    # hybrid: code's answer when it found exactly one match, otherwise the step-by-step answer.
    # sorted: the bootstrap below depends on row order, so it must not vary between runs
    for i in sorted(set(by.get("extract_code", {})) & set(by.get("cot", {}))):
        code = by["extract_code"][i]
        pick = code if code["pred"] is not None else by["cot"][i]
        by["hybrid"][i] = {**pick, "condition": "hybrid", "from_code": pick is code}
    order = [c for c in ORDER if c in by]
    pct = lambda xs: sum(xs) / len(xs)

    print(f"\n{'condition':13s} {'n':>4s} {'accuracy':>8s} {'95% CI':>16s} {'no answer':>9s} {'cut off':>8s} {'words':>6s}")
    for c in order:
        rs = list(by[c].values())
        lo, hi = ci(grouped(rs, lambda r: r["correct"]))
        print(f"{c:13s} {len(rs):4d} {pct([r['correct'] for r in rs]):8.1%} {f'[{lo:.1%}, {hi:.1%}]':>16s} "
              f"{pct([r['pred'] is None for r in rs]):9.1%} {pct([r['cut_off'] for r in rs]):8.1%} "
              f"{pct([r['output_words'] for r in rs]):6.0f}")

    empty = Counter(r["condition"] for r in rows if r.get("empty_reply"))
    if empty:
        print(f"\nwarning: empty replies (scored wrong): {dict(empty)}. Run `check` on this model.")
    ids = defaultdict(set)
    for r in rows:
        ids[r["condition"]].add(r.get("prompt_id"))
    mixed = {c: v for c, v in ids.items() if len(v) > 1}
    if mixed:
        print(f"\nwarning: these conditions mix rows from different prompt wordings: {sorted(mixed)}")

    edges = sorted({r["n_edges"] for r in rows})
    print("\naccuracy by number of relationships:")
    print(f"{'':13s} " + " ".join(f"{e:>6d}" for e in edges))
    for c in order:
        cells = [[r["correct"] for r in by[c].values() if r["n_edges"] == e] for e in edges]
        print(f"{c:13s} " + " ".join(f"{pct(a):6.0%}" if a else "     -" for a in cells))

    def paired(a, b, label):
        ids = sorted(set(by[a]) & set(by[b])) if a in by and b in by else []
        if not ids:
            return
        diffs = [{"group": by[a][i]["group"], "d": by[a][i]["correct"] - by[b][i]["correct"]} for i in ids]
        lo, hi = ci(grouped(diffs, lambda r: r["d"]))
        only_a = sum(r["d"] == 1 for r in diffs)
        only_b = sum(r["d"] == -1 for r in diffs)
        print(f"  {label:42s} {pct([r['d'] for r in diffs]):+6.1%}  CI [{lo:+.1%}, {hi:+.1%}]  "
              f"only first right: {only_a}, only second right: {only_b}")

    print("\nquestion 3 - is listing relationships special? (paired, same questions)")
    paired("extract_llm", "cot", "listing vs generic reasoning")
    paired("extract_llm", "restate", "listing vs restating the stories")
    paired("extract_llm", "cot_brief", "listing vs brief reasoning (similar length)")
    paired("extract_compare", "cot", "list-and-compare vs generic reasoning")
    paired("extract_compare", "restate", "list-and-compare vs restating")
    paired("extract_compare", "extract_llm", "list-and-compare vs listing only")
    paired("restate", "cot", "restating vs generic reasoning")
    paired("cot", "direct", "generic reasoning vs direct")
    print("  Listing is 'special' only if it beats BOTH controls with an interval above zero,")
    print("  at a similar number of words (see table above).")

    print("\nquestion 1 - reading or matching?")
    paired("gold_llm", "extract_code", "matching-only vs reading-only")
    paired("gold_cot", "gold_llm", "true relationships: reasoning vs at a glance")
    paired("gold_cot", "cot", "reasoning from true relationships vs stories")
    paired("gold_llm", "direct", "true relationships vs stories, at a glance")

    if "hybrid" in by:
        hy = list(by["hybrid"].values())
        from_code = [r["correct"] for r in hy if r["from_code"]]
        fallback = [r["correct"] for r in hy if not r["from_code"]]
        print("\nhybrid - code answers when it finds exactly one match, otherwise step-by-step reasoning")
        if from_code:
            print(f"  answered by code: {len(from_code)} questions, {pct(from_code):.1%} right")
        if fallback:
            print(f"  fell back to reasoning: {len(fallback)} questions, {pct(fallback):.1%} right")
        paired("hybrid", "cot", "hybrid vs generic reasoning")
        paired("hybrid", "extract_llm", "hybrid vs listing (model matches)")
        paired("hybrid", "gold_cot", "hybrid vs reasoning from true relationships")

    if "map_llm" in by:
        mp = [r for r in by["map_llm"].values() if r.get("mapping_right") is not None]
        print("\nrole binding - the model pairs characters before answering")
        print(f"  pairing for the true match fully right: {pct([r['mapping_right'] for r in mp]):.1%}  "
              f"(n={len(mp)}; {len(by['map_llm']) - len(mp)} replies had no readable pairings)")
        for flag, name in ((True, "was right"), (False, "was wrong")):
            sub = [r["correct"] for r in mp if r["mapping_right"] == flag]
            if sub:
                print(f"  map_llm accuracy when the true match's pairing {name}: {pct(sub):.1%}  (n={len(sub)})")
        paired("map_llm", "cot", "pairing vs generic reasoning")
        paired("map_llm", "extract_llm", "pairing vs listing relationships")
        paired("map_code", "map_llm", "code on the model's pairings vs the model")

    for a, b in (("direct", "direct_shuf"), ("gold_llm", "gold_llm_shuf")):
        ids = sorted(set(by.get(a, {})) & set(by.get(b, {})))
        if not ids:
            continue
        if a == "direct":
            print(f"\nposition check - the same question with every candidate moved {SHIFT} places")
        same_story = pct([by[a][i]["picked_role"] == by[b][i]["picked_role"] for i in ids])
        same_letter = pct([by[a][i]["pred"] == by[b][i]["pred"] for i in ids])
        print(f"  {a:9s} picked the same story in both orders: {same_story:.0%}, the same letter: {same_letter:.0%}  (n={len(ids)})")
        paired(b, a, f"{b} vs original order")

    ex = [r["extraction"] for r in by.get("extract_llm", {}).values() if r.get("extraction")]
    if ex:
        tp, npred, ngold = (sum(e[k] for e in ex) for k in ("tp", "n_pred", "n_gold"))
        p, rcl = tp / max(npred, 1), tp / max(ngold, 1)
        errs = sum((Counter(e["errors"]) for e in ex), Counter())
        print(f"\nreading (extraction): triple precision {p:.1%}, recall {rcl:.1%}, "
              f"F1 {2 * p * rcl / max(p + rcl, 1e-9):.1%}")
        print(f"  questions with all five stories read correctly: {pct([e['all_correct'] for e in ex]):.1%}")
        print(f"  missed gold triples by cause: {dict(errs)}")
        for flag, name in ((True, "was perfect"), (False, "had an error")):
            sub = [r["correct"] for r in by["extract_llm"].values()
                   if r.get("extraction") and r["extraction"]["all_correct"] == flag]
            if sub:
                print(f"  extract_llm accuracy when reading {name}: {pct(sub):.1%}  (n={len(sub)})")

    print("\nstability across reworded twins (same question, different wording):")
    for c in order:
        pairs = [v for v in grouped(by[c].values(), lambda r: r["correct"]).values() if len(v) == 2]
        if pairs:
            print(f"  {c:13s} same outcome on both wordings: {pct([a == b for a, b in pairs]):.0%}  (n={len(pairs)} pairs)")

    print("\nanswer letters chosen / wrong answers by distractor type:")
    for c in order:
        letters = Counter(r["pred"] or "none" for r in by[c].values())
        wrong = Counter(r["picked_role"] for r in by[c].values() if not r["correct"] and r["picked_role"])
        print(f"  {c:13s} {dict(sorted(letters.items()))}  |  {dict(wrong)}")

    print("\naccuracy on replies that finished (not cut off):")
    for c in order:
        fin = [r["correct"] for r in by[c].values() if not r["cut_off"]]
        print(f"  {c:15s} {pct(fin):6.1%}  (n={len(fin)})" if fin else f"  {c:15s} -")

    print("\nwrong picks: did the chosen story keep the source's relationship types?")
    print("  (by chance about 56% of distractors keep the types and 44% change one)")
    for c in order:
        w = Counter(r.get("picked_edit") for r in by[c].values() if not r["correct"] and r["pred"])
        print(f"  {c:15s} same types, wrong arrangement: {w['reverse'] + w['rewire']:3d}   one type changed: {w['relabel']:3d}")

    f = sum((Counter(e.get("forms", {})) for e in ex), Counter())
    if f:
        print("\nreading errors by sentence style:")
        for k in ("active", "passive"):
            n = max(f[k + "_n"], 1)
            print(f"  {k:8s} {f[k + '_n']:4d} relationships, missed {f[k + '_missed'] / n:.1%}, reversed {f[k + '_reversed'] / n:.1%}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def model_args(p):
        p.add_argument("--model", required=True, help="model name the server expects, or 'mock'")
        p.add_argument("--base-url", default="http://localhost:1234/v1")
        p.add_argument("--data", default="data/questions.jsonl")
        p.add_argument("--answer-cap", type=int, default=16,
                       help="output tokens for answer-only prompts (raise for models that think before answering)")
        p.add_argument("--reasoning-cap", type=int, default=REASONING_CAP,
                       help="output tokens for prompts that write before answering")
        p.add_argument("--temperature", type=lambda s: None if s == "none" else float(s), default=0.0,
                       help="sampling temperature, or 'none' to leave it out (some reasoning models reject it)")
        p.add_argument("--token-param", default="max_tokens", choices=["max_tokens", "max_completion_tokens"],
                       help="name of the output-length field (OpenAI reasoning models need max_completion_tokens)")
        p.add_argument("--extra-body", type=json.loads, default={},
                       help="JSON merged into every request, e.g. '{\"chat_template_kwargs\": {\"enable_thinking\": false}}'")

    r = sub.add_parser("run", help="run conditions and append results")
    model_args(r)
    r.add_argument("--split", default="dev", help="dev, test_familiar, ..., or all")
    r.add_argument("--conditions", default="direct,cot,cot_brief,restate,extract,extract_compare,gold,gold_cot,"
                                           "map,direct_shuf,gold_shuf")
    r.add_argument("--limit", type=int, help="about this many questions (for a quick pilot)")
    r.add_argument("--out")
    c = sub.add_parser("check", help="try a new model on a few questions before a full run")
    model_args(c)
    c.add_argument("--n", type=int, default=4)
    p = sub.add_parser("report", help="print the results report")
    p.add_argument("path")
    s = sub.add_parser("rescore", help="re-parse stored replies with the current parsers")
    s.add_argument("path")
    args = ap.parse_args()
    {"run": run, "check": check}.get(args.cmd, lambda a: None)(args)
    if args.cmd == "report":
        report(args.path)
    elif args.cmd == "rescore":
        rescore(args.path)


if __name__ == "__main__":
    main()
