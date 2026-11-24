#!/bin/sh
# Run every tool over every dataset, then score. From the working folder (BENCH_DIR,
# which holds data/ and gets docs/ and runs/):
#   sh path/to/bench/public/runall.sh                            (all four tools)
#   TOOLS="hush-core hush-share" sh path/to/bench/public/runall.sh   (only hush)
# hush is this repo unless HUSH_DIR names another copy. PYTHON_ML is a Python with
# presidio-analyzer, spaCy's en_core_web_lg and gliner installed (default python3).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
export BENCH_DIR="${BENCH_DIR:-$PWD}"
. "$HERE/env.sh"
DATASETS="${DATASETS:-piitrace nemotron nemotron-transcripts chat tab}"
for tool in ${TOOLS:-hush-core hush-share presidio gliner}; do
  case $tool in hush-*) py=python3 ;; *) py="${PYTHON_ML:-python3}" ;; esac
  for ds in $DATASETS; do
    nice -n 10 $py -I "$HERE/run.py" "$tool" "$ds"
  done
done
nice -n 10 python3 -I "$HERE/score.py"
