# RMapLLM: relationship mapping in structural analogy

Does asking a language model to write out the relationships in a story help it pick the
structurally analogous story? RMapLLM is a dataset and an evaluation pipeline for that
question. Each question gives a source story and four candidates; exactly one candidate has
the same relational structure. Relationship extraction is scored as an intermediate step.

The pipeline answers two questions:

- **Is listing relationships special?** Listing is compared against generic step-by-step
  reasoning, restating the stories, and brief reasoning, with the same output format and length cap.
- **When the model fails, is it misreading or mismatching?** Reading is scored alone (code
  matches the model's own lists) and matching is scored alone (the model gets the true relationships).

## Results so far (development set only)

Gemma 4 E4B, 4-bit, 122 dev questions, chance = 25%. The 275 test questions have not been run.

| Condition | Accuracy | 95% CI |
|---|---|---|
| Direct answer | 21.3% | 13.6–29.4 |
| Step-by-step reasoning | 43.4% | 33.6–52.8 |
| List relationships, then answer | 7.4% | 2.6–12.9 |
| Model lists, code matches | 43.4% | 34.7–52.4 |
| Hybrid: code matches if it finds one candidate, else step-by-step reasoning | 61.5% | 52.8–70.0 |
| Pair characters first, then answer | 44.3% | 35.3–53.3 |
| True relationships given, direct answer | 45.9% | 37.7–54.4 |
| True relationships given, step-by-step reasoning | 70.5% | 62.6–78.2 |

In short: listing hurts when the model does the matching and helps when code does. The model
reads relationships fairly well but loses track of which character plays which role: when its
character pairing is right it answers correctly 83% of the time, when wrong 15%. Full numbers
are in `results_dev_final.txt` (main run) and `results_dev_round2.txt` (all conditions).
The hybrid rule was chosen after seeing dev results and still needs confirming on the test splits.

**Full report:** [`docs/REPORT.md`](docs/REPORT.md) has the design, every result with figures,
design decisions and their reasons, problems found during pilots, and a hand-off section for
anyone (person or AI agent) continuing the work.

## Quick start

Python 3.10 or later; no packages to install.

```bash
python -m relmap.build                          # rebuild data/questions.jsonl (seed 13; already included)
python -m relmap.verify data/questions.jsonl    # check every label, print dataset statistics
python -m relmap.evaluate run --model mock --limit 20 --out results/mock.jsonl   # offline test, no model
```

## Evaluating a model

The evaluator talks to any server that speaks the OpenAI chat-completions format. If the
server needs a key, set the environment variable `RELMAP_API_KEY`; keys are never written to files.

**1. Check the model first.** This sends a few dev questions under five prompts, writes
nothing, and says what to change if replies come back empty, cut off or unreadable.

```bash
python -m relmap.evaluate check --model <name> --base-url <server>/v1
```

**2. Run and report.** Runs are resumable: stop at any time and rerun the same command.

```bash
python -m relmap.evaluate run --model <name> --base-url <server>/v1 --split dev
python -m relmap.evaluate report results/<name>.jsonl
```

Examples of servers:

| Server | Base URL |
|---|---|
| llama.cpp `llama-server` | `http://127.0.0.1:8080/v1` |
| vLLM | `http://localhost:8000/v1` |
| LM Studio | `http://localhost:1234/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Google Gemini (OpenAI-compatible endpoint) | `https://generativelanguage.googleapis.com/v1beta/openai` |

The Gemma results above used:

```bash
llama-server -m gemma-4-E4B_q4_0-it.gguf --host 127.0.0.1 --port 8080 -ngl 99 -c 8192 --parallel 1 --reasoning off
```

### Models that think before answering

Answer-only prompts allow 16 output tokens. Models that reason before replying (Gemma 4 with
thinking on, Qwen3, DeepSeek-R1, Gemini 2.5, OpenAI o-series) can spend those tokens on hidden
reasoning and return nothing. `check` detects this. Fixes, in order of preference:

| Option | Use |
|---|---|
| Turn thinking off on the server | llama.cpp: `--reasoning off` |
| Turn it off per request | `--extra-body '{"chat_template_kwargs": {"enable_thinking": false}}'` (tested on llama.cpp with Gemma 4; also used by vLLM and Qwen3) |
| Allow more answer tokens | `--answer-cap 2000` |
| Model rejects `temperature` or `max_tokens` | `--temperature none --token-param max_completion_tokens` |

Reasoning printed inside the reply (`<think>...</think>`, or the analysis channel of
harmony-format models) is removed before scoring and flagged in the results row. Turning
thinking off is preferred so that every model is compared under the same conditions; report
which setting you used.

## Conditions

All prompts share the same analogy rule and list of relationship types and end with
`Answer: <letter>`. Every condition that writes before answering has the same 3000-token cap.

| Name | Model sees | Writes first | Who matches | Tells us |
|---|---|---|---|---|
| `direct` | stories | nothing | model | baseline |
| `cot` | stories | step-by-step reasoning | model | effect of extra reasoning |
| `cot_brief` | stories | reasoning, asked for 150 words or fewer | model | reasoning at shorter length |
| `restate` | stories | each story in its own words | model | re-reading without structure |
| `extract_llm` | stories | every relationship as (head, TYPE, tail) | model | listing relationships |
| `extract_compare` | stories | the lists, then a comparison | model | listing plus comparison |
| `extract_code` | the lists from `extract_llm` | - | code | limited only by reading |
| `map_llm` | stories | character pairings for every candidate | model | role binding |
| `map_code` | the pairings from `map_llm` | - | code | is the pairing right |
| `gold_llm` | true relationships | nothing | model | limited only by matching |
| `gold_cot` | true relationships | step-by-step reasoning | model | matching with reasoning |
| `direct_shuf`, `gold_llm_shuf` | as `direct` / `gold_llm`, candidates moved two places | nothing | model | position bias |
| `hybrid` | derived in the report, no model calls | - | code, then model | `extract_code` if it finds one match, else `cot` |

## Dataset

397 four-choice questions (325 originals and 72 reworded twins), generated from small directed
graphs of 2 to 5 relationships over six types (AUTHORITY, SUPPLY, TEACH, PROTECT, EVALUATE,
OPPOSE) and written as short stories in nine settings. The correct answer is provable by graph
matching, and `relmap.verify` checks every label. Each question has one true match and three
distractors, each one structural edit away from the source:

- a **look-alike** with the source's setting, names and wording (a word-overlap baseline picks it 100% of the time),
- a **direction flip** (one relationship reversed),
- a **type swap** (one relationship type changed).

| Split | Questions | Purpose |
|---|---|---|
| `dev` | 122 | prompt development; all results above |
| `test_familiar` | 145 | familiar shapes and settings, unseen structures |
| `test_heldout_shape` | 60 | graph shapes that appear in no other split |
| `test_heldout_domain` | 70 | source or true match set in a setting unseen elsewhere |

Use `dev` for any tuning. Run the test splits once, after prompts are frozen.

**Human review.** `python -m relmap.review_sample` exports 40 questions to
`data/review/review_sheet.csv` (no answers) and `data/review/review_key.csv` (answers). The key
is in this repository, so annotators should be given only the sheet.

## Files

| Path | Contents |
|---|---|
| `relmap/schema.py` | relationship types, settings, names, sentence templates |
| `relmap/graphs.py` | graph matching, random graphs, single-edit distractors |
| `relmap/realize.py` | graph to story text, and text back to graph |
| `relmap/build.py` | builds questions and assigns splits |
| `relmap/verify.py` | label checks, split-leak checks, TF-IDF baseline |
| `relmap/evaluate.py` | prompts, model calls, scoring, `check`, `run`, `report`, `rescore` |
| `relmap/review_sample.py` | human-review export |
| `data/questions.jsonl` | the dataset |
| `results/gemma-4-E4B-q4.jsonl` | every Gemma reply with its score, one row per question and condition |
| `results/gemma-4-E4B-q4.pilot1.jsonl` | an early pilot before fixes; not used in any number above |
| `results_dev_final.txt`, `results_dev_round2.txt` | full report output |
| `docs/REPORT.md`, `docs/figures/` | project report and hand-off notes |

## Reproducibility

- Dataset: fixed seed (13); `relmap.build` regenerates `data/questions.jsonl` exactly.
- Model calls: temperature 0, one independent request per question, no conversation history.
- Every result row stores the model name, request settings and a fingerprint of the prompt
  wording (`prompt_id`). The report warns if one file mixes prompt wordings.
- After changing a parser, `python -m relmap.evaluate rescore results/<name>.jsonl` re-scores
  all stored replies (a `.bak` copy is kept) so old and new results are scored alike.
- Confidence intervals: bootstrap over question groups (an original and its twin), 2000 resamples, fixed seed.

## Limitations

One model so far, one prompt wording per condition, templated rather than natural text, no
human validation of labels yet, and test splits not yet run.

## Acknowledgement

Built as a course project. The dataset generator, templates and evaluation code were written
with the help of an AI assistant (Claude).

## License

MIT; see `LICENSE`.
