"""Check a built dataset and print pilot statistics.

    python -m relmap.verify data/questions.jsonl

Checks, per question:
  - every story's text parses back to exactly its stored triples
  - exactly one candidate matches the source graph, and it is the labeled answer
  - every gold entity mapping really maps source triples onto the true match
Checks, across the dataset:
  - dev and test share no labeled structure; held-out shapes appear only in their split
  - paraphrase twins sit in the same split as their original
Also reports answer-position balance and how a TF-IDF baseline behaves.
"""

import json
import math
import re
import sys
from collections import Counter, defaultdict

from . import graphs
from .realize import parse
from .schema import HELDOUT_DOMAINS


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def to_graph(triples):
    """Name triples -> id graph (ids by sorted name)."""
    names = sorted({t[0] for t in triples} | {t[2] for t in triples})
    idx = {n: i for i, n in enumerate(names)}
    return [(idx[h], r, idx[t]) for h, r, t in triples]


def check_question(q):
    errs = []
    stories = [("source", q["source"])] + [(c["label"], c) for c in q["candidates"]]
    for tag, s in stories:
        try:
            got = parse(s["domain"], s["text"])
        except ValueError as e:
            errs.append(f"{tag}: {e}")
            continue
        if got != s["triples"]:
            errs.append(f"{tag}: text parses to {got}, stored {s['triples']}")
    src = to_graph(q["source"]["triples"])
    hits = [c["label"] for c in q["candidates"] if graphs.matches(src, to_graph(c["triples"]))]
    if hits != [q["answer"]]:
        errs.append(f"matching candidates {hits}, answer {q['answer']}")
    true = next(c for c in q["candidates"] if c["label"] == q["answer"])
    if true["role"] != "true_match":
        errs.append("answer is not the true_match candidate")
    tset = {tuple(t) for t in true["triples"]}
    if not q["gold_mappings"]:
        errs.append("no gold mapping")
    for m in q["gold_mappings"]:
        if {(m[h], r, m[t]) for h, r, t in q["source"]["triples"]} != tset:
            errs.append(f"bad gold mapping {m}")
    return errs


def check_splits(qs):
    errs = []
    by = defaultdict(set)
    for q in qs:
        by[q["split"]].add(q["structure_id"])
    if by["dev"] & (by["test_familiar"] | by["test_heldout_domain"] | by["test_heldout_shape"]):
        errs.append("dev shares labeled structures with a test split")
    shapes = defaultdict(set)
    for q in qs:
        shapes[q["split"]].add(q["shape_id"])
    others = set().union(*(v for k, v in shapes.items() if k != "test_heldout_shape"))
    if shapes["test_heldout_shape"] & others:
        errs.append("held-out shapes leak into other splits")
    groups = defaultdict(set)
    for q in qs:
        groups[q["paraphrase_group"]].add(q["split"])
        doms = {q["source"]["domain"]} | {c["domain"] for c in q["candidates"]}
        if q["split"] != "test_heldout_domain" and doms & set(HELDOUT_DOMAINS):
            errs.append(f"{q['id']}: held-out domain outside its split")
    if any(len(v) > 1 for v in groups.values()):
        errs.append("a paraphrase group spans more than one split")
    return errs


def tfidf_picks(qs):
    """Which candidate role does a TF-IDF cosine baseline choose?"""
    tok = lambda s: re.findall(r"\w+", s.lower())
    docs = [tok(s["text"]) for q in qs for s in [q["source"], *q["candidates"]]]
    df = Counter(w for d in docs for w in set(d))
    idf = {w: math.log(len(docs) / n) + 1 for w, n in df.items()}

    def vec(text):
        v = Counter(tok(text))
        return {w: c * idf[w] for w, c in v.items()}

    def cos(a, b):
        dot = sum(x * b.get(w, 0) for w, x in a.items())
        return dot / (math.sqrt(sum(x * x for x in a.values())) * math.sqrt(sum(x * x for x in b.values())))

    picks = Counter()
    for q in qs:
        s = vec(q["source"]["text"])
        picks[max(q["candidates"], key=lambda c: cos(s, vec(c["text"])))["role"]] += 1
    return picks


def main():
    qs = load(sys.argv[1] if len(sys.argv) > 1 else "data/questions.jsonl")
    errors = [f"{q['id']}: {e}" for q in qs for e in check_question(q)] + check_splits(qs)
    print(f"{len(qs)} questions, {sum(not q['is_paraphrase'] for q in qs)} base + "
          f"{sum(q['is_paraphrase'] for q in qs)} paraphrase twins")
    print("split x edges:")
    table = Counter((q["split"], q["n_edges"]) for q in qs)
    for split in sorted({s for s, _ in table}):
        print(f"  {split:22s}", {e: table[(split, e)] for e in sorted({e for _, e in table})})
    print("answer positions:", dict(sorted(Counter(q["answer"] for q in qs).items())))
    print("lexical distractor edits:", dict(Counter(
        c["perturbation"] for q in qs for c in q["candidates"] if c["role"] == "lexical")))
    print("distinct structures:", len({q["structure_id"] for q in qs}),
          "| distinct shapes:", len({q["shape_id"] for q in qs}))
    picks = tfidf_picks(qs)
    print("TF-IDF baseline picks:", {k: f"{v / len(qs):.0%}" for k, v in picks.most_common()})
    if errors:
        print(f"\nFAILED: {len(errors)} problems")
        for e in errors[:20]:
            print("  ", e)
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
