# Public benchmark

This harness runs hush, Presidio and GLiNER over five openly licensed PII test sets and
scores them all with one scorer. The figures in the main README's "How it compares" came
from it. No data is kept in the repository: you download each set into a working folder of
your own, and the prepared documents, runs and scores are written there too.

## The scoring

A marked span counts as caught when none of its letters or digits is left in place. A
title in front of a name ("Mr", "Dr") may stay. Over-redaction is the number of words a
tool touched that lie in no marked span, per 1,000 words. Span precision is the share of a
tool's spans that touch a marked span. PII-TRACE has 50 dialogues with no personal data,
and the scores say how many of them each tool touched. `labels.py` maps each set's labels
and each tool's labels onto the same eight types. `score.py` has the details.

## The sets

Read each licence on its card before you download. Put the files at these paths under the
working folder:

| set | where | licence | file in the working folder | used |
|---|---|---|---|---|
| PII-TRACE | Hugging Face dataset `perplexity-ai/PII-TRACE` | MIT | `data/piitrace/train.parquet` | all 500 dialogues, 50 with no personal data |
| Nemotron-PII | Hugging Face dataset `nvidia/Nemotron-PII`, test split | CC BY 4.0 | `data/nemotron/test.parquet` | 1,000 rows drawn with seed 20261124, and separately every row whose document type contains "transcript" (196) |
| Synthetic chat logs | Hugging Face dataset `aitrainingdatabroker/synthetic-chat-logs-pii-spans` | CC BY 4.0, credit AI Training Data Broker | `data/chat/train.jsonl`, `data/chat/test.jsonl` | all 500 lines |
| TAB | GitHub `NorskRegnesentral/text-anonymisation-benchmark` | MIT | `data/tab/echr_test.json` | the 127 test cases; a span is gold when an annotator marked it DIRECT or QUASI |

The GLiNER runs use the model `knowledgator/gliner-pii-large-v1.0` from Hugging Face,
saved as `models/gliner-pii-large-v1.0` in the working folder (or set `GLINER_MODEL`).

## What it needs

- hush: the standard library only. The harness runs the hush in this repository unless
  `HUSH_DIR` names another copy, for example an earlier version unpacked with `git archive`.
- `prepare.py`: a Python with `pyarrow`.
- Presidio and GLiNER: a second Python (`PYTHON_ML`) with `presidio-analyzer`, spaCy's
  `en_core_web_lg` and `gliner`. The published runs used presidio-analyzer 2.2.366,
  spaCy 3.8.18 with en_core_web_lg 3.8.0, gliner 0.2.30 and torch 2.15.0 for CPU, on
  four threads.

## Commands

From the working folder, with `REPO` the path to this repository:

```
export BENCH_DIR="$PWD"
$PYTHON_ML -I "$REPO/bench/public/prepare.py"
TOOLS="hush-core hush-share" sh "$REPO/bench/public/runall.sh"
```

`prepare.py` writes `docs/<set>.jsonl` with the gold spans in one shape. `runall.sh` runs
each tool over each set into `runs/<tool>/<set>.jsonl` and then scores them all into
`runs/scores.json`, `runs/tables.md` and `runs/examples.json`. Leave out `TOOLS` to run
all four (hush-core, hush-share, presidio, gliner); `DATASETS` picks sets (piitrace,
nemotron, nemotron-transcripts, chat, tab). One tool on one set, or a few documents:

```
python3 -I "$REPO/bench/public/run.py" hush-share chat --limit 20
$PYTHON_ML -I "$REPO/bench/public/run.py" gliner-short piitrace
python3 -I "$REPO/bench/public/score.py"
```

`gliner` uses 30 detailed labels, `gliner-short` 10 plain ones; both are in `tools.py`,
at a threshold of 0.3. The scores moved a lot between the two lists.

To compare versions of hush, run one, then rename its run folders with a tag
(`runs/hush-core` to `runs/hush-core-TAG`, the same for `hush-share`), and run the other.
`score.py` scores every `runs/hush-core-TAG` and `runs/hush-share-TAG` it finds as extra
columns.

## Limits

All five sets are synthetic or legal text, not real call transcripts. PII-TRACE's names
are invented words, which suits hush's "not an English word" rule. hush was tuned on the
Nemotron sets and the chat lines; PII-TRACE and TAB were held out from that tuning, though
their weak categories were known beforehand. The main README says more.
