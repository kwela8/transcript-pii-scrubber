"""Run one tool over one prepared dataset and save what it found, document by document.

    python3 -I path/to/bench/public/run.py TOOL DATASET [--limit N]

TOOL is hush-core, hush-share (stdlib only: run them with the system python3),
presidio or gliner (run them with the Python that has them,
$PYTHON_ML in runall.sh). Writes runs/TOOL/DATASET.jsonl,
one line per document: {"id", "spans": [[start, end, label, score]], "seconds", "extra"},
and runs/TOOL/DATASET.meta.json with the versions and timings.
"""
import argparse
import json
import os
import pathlib
import platform
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tools  # noqa: E402

# The working folder: data/, docs/, runs/ and models/ live here, never in the repo.
ROOT = pathlib.Path(os.environ.get("BENCH_DIR", ".")).resolve()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tool")
    ap.add_argument("dataset")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    docs = [json.loads(line) for line in
            (ROOT / "docs" / ("%s.jsonl" % args.dataset)).read_text(encoding="utf-8").splitlines()]
    docs = docs[:args.limit] if args.limit else docs

    started = time.perf_counter()
    spans_of = tools.make(args.tool)
    spans_of("Warm-up: Jane Smith, 07700 900123.")       # first-call costs go with the load
    load_seconds = time.perf_counter() - started

    out_dir = ROOT / "runs" / args.tool
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0.0
    with open(out_dir / ("%s.jsonl" % args.dataset), "w", encoding="utf-8") as f:
        for n, doc in enumerate(docs, 1):
            t0 = time.perf_counter()
            spans, extra = spans_of(doc["text"])
            seconds = time.perf_counter() - t0
            total += seconds
            f.write(json.dumps({"id": doc["id"], "spans": [list(s) for s in spans],
                                "seconds": round(seconds, 5), "extra": extra},
                               ensure_ascii=False) + "\n")
            if n % 100 == 0:
                print("%s %s: %d/%d, %.1f s" % (args.tool, args.dataset, n, len(docs), total),
                      flush=True)
    meta = {"tool": args.tool, "dataset": args.dataset, "docs": len(docs),
            "version": tools.version(args.tool), "python": platform.python_version(),
            "threads": tools.THREADS, "load_seconds": round(load_seconds, 2),
            "run_seconds": round(total, 2),
            "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out_dir / ("%s.meta.json" % args.dataset)).write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
