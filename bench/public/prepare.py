"""Turn the downloaded benchmarks into one shape, docs/<dataset>.jsonl:

    {"id": ..., "text": ..., "gold": [{"start", "end", "label", "type", "mask", ...}]}

`label` is the dataset's own label, `type` the shared one (labels.py), `mask` whether the
span must be removed (always true except TAB's NO_MASK mentions). The downloads are read
as data only. Run with a Python that has pyarrow, from the working folder:

    $PYTHON_ML -I path/to/bench/public/prepare.py
"""
import ast
import json
import os
import pathlib
import random
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from labels import CHAT, NEMOTRON, PIITRACE, TAB  # noqa: E402

# The working folder: data/, docs/, runs/ and models/ live here, never in the repo.
ROOT = pathlib.Path(os.environ.get("BENCH_DIR", ".")).resolve()
DATA, DOCS = ROOT / "data", ROOT / "docs"
SEED = 20261124
NEMOTRON_N = 1000


def checked(text, gold, doc_id):
    bad = [g for g in gold if not (0 <= g["start"] < g["end"] <= len(text))]
    if bad:
        raise SystemExit("%s: %d spans out of range" % (doc_id, len(bad)))
    return gold


def nemotron():
    import pyarrow.parquet as pq
    rows = pq.read_table(DATA / "nemotron" / "test.parquet").to_pylist()

    def doc(r):
        gold, mismatched = [], 0
        for s in ast.literal_eval(r["spans"]):          # a list of dicts as a Python literal
            if r["text"][s["start"]:s["end"]].casefold() != str(s.get("text", "")).casefold():
                mismatched += 1
            gold.append({"start": s["start"], "end": s["end"], "label": s["label"],
                         "type": NEMOTRON[s["label"]], "mask": True})
        return {"id": r["uid"] + ":" + r["locale"], "text": r["text"],
                "doc_type": r["document_type"],
                "locale": r["locale"], "format": r["document_format"],
                "gold": checked(r["text"], gold, r["uid"]), "mismatched": mismatched}

    picked = random.Random(SEED).sample(range(len(rows)), NEMOTRON_N)
    write("nemotron", [doc(rows[i]) for i in picked])
    transcripts = [i for i, r in enumerate(rows) if "transcript" in r["document_type"].lower()]
    write("nemotron-transcripts", [doc(rows[i]) for i in transcripts])

MONTHS = {m: i for i, m in enumerate(("january february march april may june july august "
                                      "september october november december").split(), 1)}


def entity_key(label, value):
    """PII-TRACE's public file has no entity ids, so mentions are grouped by value: case,
    spaces and punctuation ignored, "at" and "dot" read as @ and ., dates read as
    year-month-day. Person mentions are joined to a fuller name later (piitrace)."""
    v = value.casefold()
    if label == "private_email":
        v = re.sub(r"\s+at\s+", "@", re.sub(r"\s+dot\s+", ".", v))
    if label == "private_date":
        iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
        words = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z]+),? (\d{4})", v)
        words2 = re.fullmatch(r"([a-z]+) (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})", v)
        if iso:
            v = "%s-%02d-%02d" % (iso[1], int(iso[2]), int(iso[3]))
        elif words and words[2] in MONTHS:
            v = "%s-%02d-%02d" % (words[3], MONTHS[words[2]], int(words[1]))
        elif words2 and words2[1] in MONTHS:
            v = "%s-%02d-%02d" % (words2[3], MONTHS[words2[1]], int(words2[2]))
    return label + ":" + re.sub(r"[^0-9a-z@.-]" if label == "private_date" else r"[^0-9a-z@]",
                                "", v)


def piitrace():
    import pyarrow.parquet as pq
    docs = []
    for r in pq.read_table(DATA / "piitrace" / "train.parquet").to_pylist():
        text, where = "", {}
        for t in r["turns"]:
            for role, name in (("user", "User"), ("assistant", "Assistant")):
                text += name + ": "
                where[(t["turn"], role)] = len(text)
                text += t[role] + "\n\n"
        gold = []
        for s in r["spans"]:
            start = where[(s["turn"], s["source"])] + s["start"]
            end = start + (s["end"] - s["start"])
            if text[start:end] != s["text"]:
                raise SystemExit("%s: span text does not match" % r["id"])
            gold.append({"start": start, "end": end, "label": s["label"],
                         "type": PIITRACE[s["label"]], "mask": True,
                         "entity": entity_key(s["label"], s["text"])})
        people = sorted({g["entity"] for g in gold if g["label"] == "private_person"},
                        key=lambda k: -len(k))
        names = {g["entity"]: set(g_text.casefold().split()) for g, g_text in
                 ((g, text[g["start"]:g["end"]]) for g in gold if g["label"] == "private_person")}
        for g in gold:              # "Wynora" joins "Wynora Elmquill" when it is part of it
            if g["label"] == "private_person":
                fuller = [k for k in people if names[g["entity"]] < names[k]]
                if fuller:
                    g["entity"] = fuller[0]
        docs.append({"id": r["id"], "text": text.rstrip("\n") + "\n",
                     "gold": checked(text, gold, r["id"])})
    write("piitrace", docs)


def tab():
    cases = json.loads((DATA / "tab" / "echr_test.json").read_text(encoding="utf-8"))
    docs = []
    for case in cases:
        gold = []
        for annotator, ann in sorted(case["annotations"].items()):
            for m in ann["entity_mentions"]:
                gold.append({"start": m["start_offset"], "end": m["end_offset"],
                             "label": m["entity_type"], "type": TAB[m["entity_type"]],
                             "mask": m["identifier_type"] in ("DIRECT", "QUASI"),
                             "direct": m["identifier_type"] == "DIRECT",
                             "annotator": annotator, "entity": m["entity_id"]})
        docs.append({"id": case["doc_id"], "text": case["text"],
                     "gold": checked(case["text"], gold, case["doc_id"])})
    write("tab", docs)


def chat():
    docs = []
    for split in ("train", "test"):
        for line in (DATA / "chat" / ("%s.jsonl" % split)).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            gold = [{"start": e["start"], "end": e["end"], "label": e["label"],
                     "type": CHAT[e["label"]], "mask": True} for e in row["entities"]]
            docs.append({"id": row["id"], "text": row["text"],
                         "gold": checked(row["text"], gold, row["id"])})
    write("chat", docs)


def write(name, docs):
    DOCS.mkdir(exist_ok=True)
    with open(DOCS / ("%s.jsonl" % name), "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    spans = sum(len(d["gold"]) for d in docs)
    print("%-22s %5d docs %7d gold spans" % (name, len(docs), spans))


if __name__ == "__main__":
    piitrace()
    nemotron()
    tab()
    chat()
    for name, m in (("PII-TRACE", PIITRACE), ("Nemotron", NEMOTRON), ("TAB", TAB), ("chat", CHAT)):
        if m.unknown:
            print("%s labels with no mapping, counted as OTHER: %s" % (name, sorted(m.unknown)))
