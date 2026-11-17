"""Build the four-choice analogy dataset.

    python -m relmap.build --out data/questions.jsonl

Each question: one source story and four candidates.
  true_match      same structure, different domain and names
  lexical         same domain, names and wording as the source, one edit to the structure
  direction_flip  another domain, one edge reversed
  label_swap      another domain, one relation type changed

Splits (a question's split is decided by its structure, never at random):
  dev / test_familiar   familiar shapes and domains; labeled structures never shared
  test_heldout_shape    unlabeled shapes that appear in no other split
  test_heldout_domain   source or true match set in a domain unseen elsewhere
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from . import graphs
from .realize import new_style, render
from .schema import DOMAINS, FAMILIAR_DOMAINS, HELDOUT_DOMAINS, RELATIONS

RELS = list(RELATIONS)
LETTERS = "ABCD"
# Base questions per (split, number of edges).
QUOTA = {"dev": 25, "test_familiar": 30, "test_heldout_shape": 15, "test_heldout_domain": 15}


def shape_is_heldout(edges):
    return int(graphs.shape_id(edges).split("-")[1], 16) % 5 == 0


def structure_is_dev(edges):
    return int(graphs.structure_id(edges), 16) % 2 == 0


def sample_graph(rng, split, n_edges):
    """Rejection-sample a source graph that belongs in `split`."""
    for _ in range(5000):
        g = graphs.random_graph(rng, n_edges, RELS)
        held = shape_is_heldout(g)
        ok = {
            "dev": not held and structure_is_dev(g),
            "test_familiar": not held and not structure_is_dev(g),
            "test_heldout_shape": held,
            "test_heldout_domain": not held and not structure_is_dev(g),
        }[split]
        if ok and graphs.perturbations(g, "reverse", RELS):
            return g
    return None


def make_spec(rng, split, n_edges):
    g = sample_graph(rng, split, n_edges)
    if g is None:
        return None
    n = graphs.n_nodes(g)
    if split == "test_heldout_domain":
        src_dom = rng.choice(HELDOUT_DOMAINS if rng.random() < 0.67 else FAMILIAR_DOMAINS)
        tgt_pool = HELDOUT_DOMAINS if src_dom in FAMILIAR_DOMAINS else list(DOMAINS)
        other_pool = list(DOMAINS)
    else:
        src_dom = rng.choice(FAMILIAR_DOMAINS)
        tgt_pool = other_pool = FAMILIAR_DOMAINS

    def pick(pool):
        return rng.choice([d for d in pool if d != src_dom])

    def names(dom):
        return rng.sample(DOMAINS[dom]["names"], n)

    src = {"domain": src_dom, "names": names(src_dom), "edges": g}

    perm = list(range(n))
    rng.shuffle(perm)
    tgt_dom = pick(tgt_pool)
    cands = [{"role": "true_match", "perturbation": None, "domain": tgt_dom, "names": names(tgt_dom),
              "edges": [(perm[u], r, perm[v]) for u, r, v in g]}]

    kinds = [k for k in ("reverse", "relabel", "rewire") if graphs.perturbations(g, k, RELS)]
    k = rng.choice(kinds)
    cands.append({"role": "lexical", "perturbation": k, "domain": src_dom, "names": src["names"],
                  "edges": rng.choice(graphs.perturbations(g, k, RELS))})
    for role, k in (("direction_flip", "reverse"), ("label_swap", "relabel")):
        dom = pick(other_pool)
        cands.append({"role": role, "perturbation": k, "domain": dom, "names": names(dom),
                      "edges": rng.choice(graphs.perturbations(g, k, RELS))})
    return {"split": split, "source": src, "candidates": cands}


def new_styles(rng, spec, avoid=None):
    """Surface choices for all five stories. The lexical distractor copies the source's."""
    def st(story, prev):
        return new_style(rng, story["domain"], len(story["edges"]), prev)
    src = st(spec["source"], avoid and avoid["source"])
    cands = [src if c["role"] == "lexical" else st(c, avoid and avoid["candidates"][i])
             for i, c in enumerate(spec["candidates"])]
    return {"source": src, "candidates": cands}


def assemble(rng, spec, styles, qid, group, answer_pos, is_paraphrase):
    src = spec["source"]
    g = src["edges"]

    def story(s, style):
        text, triples = render(s["domain"], s["names"], s["edges"], style)
        return {"domain": s["domain"], "entities": sorted(s["names"]), "triples": triples, "text": text}

    built = []
    for c, style in zip(spec["candidates"], styles["candidates"]):
        built.append({"role": c["role"], "perturbation": c["perturbation"], **story(c, style)})
    true, rest = built[0], built[1:]
    rng.shuffle(rest)
    rest.insert(answer_pos, true)
    for letter, c in zip(LETTERS, rest):
        c["label"] = letter

    t = spec["candidates"][0]
    mappings = [{src["names"][i]: t["names"][p[i]] for i in range(len(p))}
                for p in graphs.isomorphisms(g, t["edges"])]
    return {
        "id": qid, "split": spec["split"], "paraphrase_group": group, "is_paraphrase": is_paraphrase,
        "n_edges": len(g), "n_entities": graphs.n_nodes(g),
        "shape_id": graphs.shape_id(g), "structure_id": graphs.structure_id(g),
        "relation_types": sorted({r for _, r, _ in g}),
        "source": story(src, styles["source"]),
        "candidates": rest, "answer": LETTERS[answer_pos], "gold_mappings": mappings,
    }


def build(seed=13, edge_counts=(2, 3, 4, 5), scale=1.0, paraphrase_rate=0.2):
    rng = random.Random(seed)
    questions, pos = [], Counter()
    for split, quota in QUOTA.items():
        for n_edges in edge_counts:
            made = 0
            for _ in range(round(quota * scale)):
                spec = make_spec(rng, split, n_edges)
                if spec is None:
                    continue
                made += 1
                qid = f"q{len([q for q in questions if not q['is_paraphrase']]):04d}"
                styles = new_styles(rng, spec)
                questions.append(assemble(rng, spec, styles, qid, qid, pos[split] % 4, False))
                pos[split] += 1
                if rng.random() < paraphrase_rate:
                    twin = new_styles(rng, spec, avoid=styles)
                    questions.append(assemble(rng, spec, twin, qid + "-p", qid, pos[split] % 4, True))
                    pos[split] += 1
            if made < round(quota * scale):
                print(f"note: {split} with {n_edges} edges: only {made} questions (no eligible structures)")
    return questions


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/questions.jsonl")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--edges", default="2,3,4,5", help="edge counts to include")
    ap.add_argument("--scale", type=float, default=1.0, help="multiply all quotas (0.1 for a pilot)")
    args = ap.parse_args()
    qs = build(args.seed, tuple(int(x) for x in args.edges.split(",")), args.scale)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for q in qs:
            f.write(json.dumps(q) + "\n")
    print(f"wrote {len(qs)} questions to {out}")


if __name__ == "__main__":
    main()
