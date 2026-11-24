"""Score every run against the gold spans. Standard library only.

    python3 -I path/to/bench/public/score.py

The leak test: a gold span is caught when none of its letters or digits survive in place,
that is, every one of them lies inside a span the tool removed. A title in front of a name
("Mr", "Dr") may survive. Over-redaction counts the words a tool touched that lie in no
gold span, per 1,000 words. Span precision is the share of the tool's merged spans that
touch a gold span. Writes runs/scores.json, runs/tables.md, runs/examples.json and, per
tool and dataset, runs/TOOL/DATASET.scored.jsonl for reading one document at a time.
"""
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from labels import TYPES, tool_type  # noqa: E402

# The working folder: data/, docs/, runs/ and models/ live here, never in the repo.
ROOT = pathlib.Path(os.environ.get("BENCH_DIR", ".")).resolve()
BASE_TOOLS = ("hush-core", "hush-share", "presidio", "gliner", "gliner-short")
TOOL_NAMES = {"hush-core": "ours: core", "hush-share": "ours: share",
              "presidio": "Presidio", "gliner": "GLiNER, 30 labels",
              "gliner-short": "GLiNER, 10 labels"}
# Kept runs of earlier versions of ours sit beside the current ones as
# runs/hush-core-TAG and runs/hush-share-TAG, and are scored too.
VARIANTS = tuple(sorted(p.name for p in (ROOT / "runs").glob("hush-*-*") if p.is_dir()
                        and p.name.split("-")[1] in ("core", "share")))
TOOLS = BASE_TOOLS[:2] + VARIANTS + BASE_TOOLS[2:]
for _v in VARIANTS:
    _base, _tag = _v.split("-", 2)[1], _v.split("-", 2)[2]
    TOOL_NAMES[_v] = "ours: %s, %s" % (_base, _tag)
DATASETS = ("piitrace", "nemotron", "nemotron-transcripts", "chat", "tab")
WORD = re.compile(r"\w+")
TITLES = {"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "dame"}
# TAB's own scorer also lets these survive: its ignored tokens, and (approximately, as a
# word list in place of its spaCy part-of-speech test) determiners, prepositions,
# conjunctions and particles.
TAB_IGNORE = TITLES | {"no", "nr", "about", "the", "a", "an", "this", "that", "these", "those",
                       "of", "in", "on", "at", "for", "to", "by", "with", "from", "into",
                       "under", "between", "and", "or", "s", "not"}


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def mask_of(n, spans):
    cov = bytearray(n)
    for s, e in spans:
        s, e = max(0, s), min(n, e)
        if e > s:
            cov[s:e] = b"\x01" * (e - s)
    return cov


def merged(spans):
    out = []
    for s, e, kind in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
            out[-1][2].add(kind)
        else:
            out.append([s, e, {kind}])
    return out


def caught(text, cov, start, end, ignore):
    for m in WORD.finditer(text, start, end):
        if m.group(0).lower() in ignore:
            continue
        if any(text[i].isalnum() and not cov[i] for i in range(m.start(), m.end())):
            return False
    return True


def score_doc(doc, run, tool, ignore):
    text, n = doc["text"], len(doc["text"])
    gold = [g for g in doc["gold"] if g["mask"]]
    pred = [(s, e, tool_type(tool, label)) for s, e, label, _score in run["spans"]]
    cov = mask_of(n, [(s, e) for s, e, _ in pred])
    by_type = {t: mask_of(n, [(s, e) for s, e, k in pred if k == t]) for t in TYPES}
    gold_cov = mask_of(n, [(g["start"], g["end"]) for g in gold])

    hits = [caught(text, cov, g["start"], g["end"], ignore) for g in gold]
    typed = [caught(text, by_type[g["type"]], g["start"], g["end"], ignore) for g in gold]
    words = [m.span() for m in WORD.finditer(text)]
    over = [text[a:b] for a, b in words if any(cov[a:b]) and not any(gold_cov[a:b])]
    spans = [m for m in merged(pred) if any(ch.isalnum() for ch in text[m[0]:m[1]])]
    touching = sum(1 for s, e, _ in spans if any(gold_cov[s:e]))
    redacted, cursor = [], 0
    for s, e, kinds in spans:
        redacted += [text[cursor:s], "[%s]" % "/".join(sorted(kinds))]
        cursor = e
    redacted.append(text[cursor:])
    chars = [0, 0, 0]                  # untyped, non-space characters: both, tool, gold
    for i, ch in enumerate(text):
        if not ch.isspace() and (cov[i] or gold_cov[i]):
            chars[0] += cov[i] and gold_cov[i]
            chars[1] += cov[i]
            chars[2] += gold_cov[i]
    leaks = [{"start": g["start"], "end": g["end"], "label": g["label"], "type": g["type"],
              "text": text[g["start"]:g["end"]]} for g, hit in zip(gold, hits) if not hit]
    return {"gold": gold, "hits": hits, "typed": typed, "words": len(words), "over": over,
            "spans": len(spans), "touching": touching, "leaks": leaks,
            "redacted": "".join(redacted), "cov": cov, "chars": chars}


def bucket(n):
    return "1" if n == 1 else "2-5" if n <= 5 else "6+"


def entity_coverage(gold, hits):
    """Every-mention coverage: an entity counts only when all its mentions are caught."""
    groups = {}
    for g, hit in zip(gold, hits):
        if "entity" in g and "annotator" not in g:
            groups.setdefault(g["entity"], []).append(hit)
    return [(bucket(len(v)), all(v)) for v in groups.values()]


def tab_metrics(doc, cov):
    """TAB's own measures (Pilan et al. 2022, section 6), micro-averaged over annotators,
    with uniform token weights: token recall R, entity recall on direct (ER_di) and quasi
    (ER_qi) identifiers, and token precision P."""
    text = doc["text"]
    out = {"r": [0, 0], "er_di": [0, 0], "er_qi": [0, 0], "p": [0.0, 0]}
    entities = {}
    for g in doc["gold"]:
        e = entities.setdefault((g["annotator"], g["entity"]),
                                {"direct": g["direct"], "need": False, "ok": True})
        e["need"] = e["need"] or g["mask"]
        if g["mask"]:
            ok = caught(text, cov, g["start"], g["end"], TAB_IGNORE)
            e["ok"] = e["ok"] and ok
            for m in WORD.finditer(text, g["start"], g["end"]):
                out["r"][1] += 1
                out["r"][0] += caught(text, cov, m.start(), m.end(), TAB_IGNORE)
    for e in entities.values():
        if e["need"]:
            key = "er_di" if e["direct"] else "er_qi"
            out[key][1] += 1
            out[key][0] += e["ok"]
    annotators = {g["annotator"] for g in doc["gold"]}
    masked_by = [(g["start"], g["end"], g["annotator"]) for g in doc["gold"] if g["mask"]]
    i = 0
    while i < len(cov):                      # every run of removed text, cut into words
        if not cov[i]:
            i += 1
            continue
        j = i
        while j < len(cov) and cov[j]:
            j += 1
        for m in WORD.finditer(text, i, j):
            who = {a for s, e, a in masked_by if s <= m.start() and e >= m.end()}
            out["p"][0] += len(who)
            out["p"][1] += len(annotators)
        i = j
    return out


def ratio(a, b):
    return round(a / b, 4) if b else None


def main():
    scores, examples, catches = {}, {}, {}
    for ds in DATASETS:
        docs_path = ROOT / "docs" / ("%s.jsonl" % ds)
        if not docs_path.exists():
            continue
        docs = load(docs_path)
        ignore = TAB_IGNORE if ds == "tab" else TITLES
        scores[ds] = {"docs": len(docs), "words": sum(len(WORD.findall(d["text"])) for d in docs),
                      "gold": {t: sum(1 for d in docs for g in d["gold"]
                                      if g["mask"] and g["type"] == t) for t in TYPES},
                      "tools": {}}
        for tool in TOOLS:
            run_path = ROOT / "runs" / tool / ("%s.jsonl" % ds)
            if not run_path.exists():
                continue
            runs = {r["id"]: r for r in load(run_path)}
            if len(runs) != len(docs):
                print("skip %s %s: %d of %d docs run" % (tool, ds, len(runs), len(docs)))
                continue
            meta = json.loads((run_path.parent / ("%s.meta.json" % ds)).read_text())
            agg = {t: [0, 0, 0] for t in TYPES}           # caught, typed-caught, total
            by_label, words, over, spans, touching = {}, 0, 0, 0, 0
            person_docs, person_leak_docs, refused, diffed, seconds = 0, 0, 0, 0, 0.0
            tab = {"r": [0, 0], "er_di": [0, 0], "er_qi": [0, 0], "p": [0.0, 0]}
            leaks_out, chars, entities = [], [0, 0, 0], {}
            controls = [0, 0, 0, 0]          # docs, docs with anything removed, words removed, words
            with open(run_path.with_suffix(".scored.jsonl"), "w", encoding="utf-8") as f:
                for doc in docs:
                    run = runs[doc["id"]]
                    s = score_doc(doc, run, tool, ignore)
                    for k, (g, hit, typed_hit) in enumerate(zip(s["gold"], s["hits"], s["typed"])):
                        a = agg[g["type"]]
                        a[0] += hit
                        a[1] += typed_hit
                        a[2] += 1
                        lab = by_label.setdefault(g["label"], [0, 0])
                        lab[0] += hit
                        lab[1] += 1
                        catches.setdefault((ds, doc["id"], g["start"], g["end"], g.get("annotator")),
                                           {"type": g["type"]})[tool] = hit
                    words += s["words"]
                    over += len(s["over"])
                    spans += s["spans"]
                    touching += s["touching"]
                    if any(g["type"] == "PERSON" for g in s["gold"]):
                        person_docs += 1
                        person_leak_docs += any(l["type"] == "PERSON" for l in s["leaks"])
                    chars = [a + b for a, b in zip(chars, s["chars"])]
                    for size, ok in entity_coverage(s["gold"], s["hits"]):
                        e = entities.setdefault(size, [0, 0])
                        e[0] += ok
                        e[1] += 1
                    if not s["gold"]:
                        controls[0] += 1
                        controls[1] += bool(s["over"])
                        controls[2] += len(s["over"])
                        controls[3] += s["words"]
                    refused += bool(run["extra"].get("refused"))
                    diffed += run["extra"].get("aligned") == "diff"
                    seconds += run["seconds"]
                    if ds == "tab":
                        for key, (num, den) in tab_metrics(doc, s["cov"]).items():
                            tab[key][0] += num
                            tab[key][1] += den
                    for leak in s["leaks"]:
                        a, b = max(0, leak["start"] - 50), leak["end"] + 50
                        leaks_out.append(dict(leak, doc=doc["id"],
                                              context=doc["text"][a:b].replace("\n", " ")))
                    f.write(json.dumps({"id": doc["id"], "leaks": s["leaks"],
                                        "over_redacted": s["over"][:100],
                                        "redacted": s["redacted"]}, ensure_ascii=False) + "\n")
            core = [t for t in TYPES if t != "OTHER"]
            result = {
                "recall": {t: ratio(agg[t][0], agg[t][2]) for t in TYPES},
                "typed_recall": {t: ratio(agg[t][1], agg[t][2]) for t in TYPES},
                "recall_all": ratio(sum(a[0] for a in agg.values()), sum(a[2] for a in agg.values())),
                "recall_without_other": ratio(sum(agg[t][0] for t in core), sum(agg[t][2] for t in core)),
                "recall_by_label": {k: [v[0], v[1], ratio(*v)] for k, v in sorted(by_label.items())},
                "span_precision": ratio(touching, spans),
                "spans": spans,
                "over_redacted_words": over,
                "over_per_1000_words": round(1000 * over / words, 2) if words else None,
                "person_leak_docs": [person_leak_docs, person_docs, ratio(person_leak_docs, person_docs)],
                "seconds_per_1000_docs": round(1000 * seconds / len(docs), 2),
                "load_seconds": meta["load_seconds"],
                "version": meta["version"], "python": meta["python"],
            }
            p, r = ratio(chars[0], chars[1]), ratio(chars[0], chars[2])
            result["char_level"] = {"precision": p, "recall": r,
                                    "f1": round(2 * p * r / (p + r), 4) if p and r else 0.0}
            if entities:
                result["every_mention_coverage"] = {k: [v[0], v[1], ratio(*v)]
                                                    for k, v in sorted(entities.items())}
            if controls[0]:
                result["controls"] = {"docs": controls[0], "docs_with_removals": controls[1],
                                      "words_removed": controls[2],
                                      "removed_per_1000_words": round(1000 * controls[2] / controls[3], 2)}
            if tool.startswith("hush-share"):
                result["refused_docs"] = refused
            if tool.startswith("hush"):
                result["aligned_by_diff"] = diffed
            if ds == "tab":
                result["tab"] = {k: ratio(v[0], v[1]) for k, v in tab.items()}
            scores[ds]["tools"][tool] = result
            examples.setdefault(ds, {})[tool] = leaks_out[:400]
    scores["exclusive"] = exclusive(catches)
    (ROOT / "runs" / "scores.json").write_text(json.dumps(scores, indent=1, ensure_ascii=False))
    (ROOT / "runs" / "examples.json").write_text(json.dumps(examples, indent=1, ensure_ascii=False))
    (ROOT / "runs" / "tables.md").write_text(tables(scores))
    print(tables(scores))


def exclusive(catches):
    """Per dataset and type: gold spans only one tool caught, and only one tool missed."""
    out = {}
    for (ds, *_), row in catches.items():
        tools = [t for t in BASE_TOOLS[:4] if t in row]
        if len(tools) < 4:
            continue
        slot = out.setdefault(ds, {}).setdefault(row["type"], {t: {"only_caught": 0, "only_missed": 0}
                                                                for t in BASE_TOOLS[:4]})
        got = [t for t in tools if row[t]]
        if len(got) == 1:
            slot[got[0]]["only_caught"] += 1
        if len(got) == len(tools) - 1:
            slot[next(t for t in tools if not row[t])]["only_missed"] += 1
    return out


def pct(x):
    return "n/a" if x is None else "%.1f%%" % (100 * x)


def tables(scores):
    lines = []
    for ds, s in scores.items():
        if ds == "exclusive" or not s["tools"]:
            continue
        tools = [t for t in TOOLS if t in s["tools"]]
        lines += ["### %s (%d documents, %d words)" % (ds, s["docs"], s["words"]), "",
                  "| | " + " | ".join(TOOL_NAMES[t] for t in tools) + " |",
                  "|---|" + "---:|" * len(tools)]
        for t in TYPES:
            if s["gold"][t]:
                lines.append("| %s recall (n=%d) | " % (t, s["gold"][t]) +
                             " | ".join(pct(s["tools"][x]["recall"][t]) for x in tools) + " |")
        rows = [("All types recall", lambda r: pct(r["recall_all"])),
                ("All but OTHER recall", lambda r: pct(r["recall_without_other"])),
                ("Span precision", lambda r: pct(r["span_precision"])),
                ("Over-redaction per 1,000 words", lambda r: "%.1f" % r["over_per_1000_words"]),
                ("Documents with a PERSON leak", lambda r: "%d of %d (%s)" % (
                    r["person_leak_docs"][0], r["person_leak_docs"][1], pct(r["person_leak_docs"][2]))),
                ("Seconds per 1,000 documents", lambda r: "%.1f" % r["seconds_per_1000_docs"])]
        for name, f in rows:
            lines.append("| %s | " % name + " | ".join(f(s["tools"][x]) for x in tools) + " |")
        extra_rows = []
        for size in ("1", "2-5", "6+"):
            got = [s["tools"][x].get("every_mention_coverage", {}).get(size) for x in tools]
            if any(got):
                extra_rows.append("| Entities with every mention caught, %s mention%s (n=%d) | " % (
                    size, "" if size == "1" else "s", next(g for g in got if g)[1]) +
                    " | ".join(pct(g[2]) if g else "n/a" for g in got) + " |")
        ctl = [s["tools"][x].get("controls") for x in tools]
        if all(ctl):
            extra_rows.append("| Documents with no PII that lost a word (of %d) | " % ctl[0]["docs"] +
                              " | ".join("%d (%.1f words per 1,000)" % (c["docs_with_removals"],
                                                                         c["removed_per_1000_words"])
                                         for c in ctl) + " |")
        extra_rows.append("| Character-level P / R / F1 | " + " | ".join(
            "%.3f / %.3f / %.3f" % (s["tools"][x]["char_level"]["precision"] or 0,
                                    s["tools"][x]["char_level"]["recall"] or 0,
                                    s["tools"][x]["char_level"]["f1"]) for x in tools) + " |")
        lines += extra_rows
        if ds == "tab":
            lines += ["", "TAB's own measures (test split, micro-averaged over annotators):", "",
                      "| | R di+qi | ER di | ER qi | P di+qi |", "|---|---:|---:|---:|---:|",
                      "| Presidio 2.2.23 default, published (Pilan et al. 2022, Table 7) "
                      "| 0.707 | 0.460 | 0.758 | 0.761 |"]
            for x in tools:
                m = s["tools"][x]["tab"]
                lines.append("| %s | %.3f | %.3f | %.3f | %.3f |" % (
                    TOOL_NAMES[x], m["r"], m["er_di"], m["er_qi"], m["p"]))
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
