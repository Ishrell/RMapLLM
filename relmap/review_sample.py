"""Export a stratified sample of questions for human review.

    python -m relmap.review_sample --n 40

Writes two files to data/review/:
  review_sheet.csv  what annotators fill in (no answers, no distractor labels)
  review_key.csv    the answer key, kept away from annotators until they finish

Each annotator works on their own copy of the sheet, independently.
The sample is spread evenly over split x number of relationships, originals only.
"""

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

from .verify import load


def sample(qs, n, seed):
    rng = random.Random(seed)
    cells = defaultdict(list)
    for q in qs:
        if not q["is_paraphrase"]:
            cells[(q["split"], q["n_edges"])].append(q)
    for group in cells.values():
        rng.shuffle(group)
    picked, keys = [], sorted(cells)
    while len(picked) < n and any(cells.values()):
        for k in keys:
            if cells[k] and len(picked) < n:
                picked.append(cells[k].pop())
    rng.shuffle(picked)
    return picked


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/questions.jsonl")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/review")
    args = ap.parse_args()

    picked = sample(load(args.data), args.n, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "review_sheet.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "id", "source_story", "A", "B", "C", "D",
                    "your_answer (A-D)", "natural (1-5)", "more_than_one_fits (y/n)", "notes"])
        for i, q in enumerate(picked, 1):
            w.writerow([i, q["id"], q["source"]["text"], *(c["text"] for c in q["candidates"]), "", "", "", ""])
    with (out / "review_key.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "id", "answer", "split", "n_relationships", "A_type", "B_type", "C_type", "D_type"])
        for i, q in enumerate(picked, 1):
            w.writerow([i, q["id"], q["answer"], q["split"], q["n_edges"], *(c["role"] for c in q["candidates"])])
    print(f"wrote {len(picked)} questions to {out / 'review_sheet.csv'} (key: {out / 'review_key.csv'})")


if __name__ == "__main__":
    main()
