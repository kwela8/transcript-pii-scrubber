"""The bench: how many names and identifiers get through, on any test set and any config.

    python3 bench/bench.py CASES.json [--config FILE] [--json] [--misses N]

A test set is one JSON file:

    {"version": "general-cases-1",
     "unscored": ["ORG"],                       # span kinds to leave out of the scores
     "cases": [{"id": "g001", "shape": "support_call", "text": "...",
                "roster": [{"first": "...", "last": "...", "preferred": null,
                            "role": "customer"}],      # known people, optional
                "keep": [{"first": "...", "last": "..."}],   # names to keep, optional
                "spans": [{"value": "...", "kind": "PERSON", "on_roster": "no"},
                          {"value": "...", "kind": "KEEP"}]}],
     "negatives": [{"id": "gn001", "shape": "...", "text": "..."}]}

``on_roster`` says whether a name is on the case's known list: "yes", "variant" (a known
person written another way: a nickname, an initial, a misspelling) or "no". The test sets
in ``bench/education/`` are in this shape, and ``bench/general/cases.json`` is a set of
general text written for this bench.

How a value is scored. The text is scrubbed into tokens; each occurrence of a listed value
is lined up with the output character by character (difflib). It is **caught** when none
of its letters or digits survive where it stood, so taking "Aisha" and leaving "Khan"
from "Aisha Khan" is a miss. A title kept in front of a name ("Mrs [person 1]") names no
one and is not a leak. Recall is caught occurrences over occurrences. A KEEP span is the
other way round: it is **intact** when every letter and digit of it survives.

A negative is a **false positive** when a name kind (PERSON, a known person's role,
CLINICIAN, PLACE) takes anything from it. Dates, codes and long numbers are taken by policy
and do not count. **Extra names** counts, over the positive cases, the name tokens that
cover no listed value: words wrongly taken as names, or names the tester did not list.

The columns run from "patterns only" (the config's packs, detectors and words and the
capitalised-name guess with no filter, no people layer) up to the config's own preset with
the known people. ``restore`` checks that every scrub restores to the original text
exactly.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hush import Hush, Person, core, residual  # noqa: E402
from hush.config import Config, load  # noqa: E402
from hush.core import fold  # noqa: E402


def columns(config):
    """The bench's columns for one config, as (name, Hush options, known people on)."""
    preset = Hush(config=config).preset
    return (
        ("patterns only", dict(names=False, rules=False, guess=True, guess_filter=False), False),
        ("+ first-name list", dict(names=True, any_case=False, guess=True), False),
        ("+ list, any case", dict(names=True, any_case=True, guess=True), False),
        ("+ known people", dict(names=True, any_case=False, guess=True), True),
        ("%s preset" % preset.name, dict(names=preset.names, any_case=preset.any_case,
                                         guess=preset.guess), True),
        ("logs preset", dict(names=True, any_case=True, guess=False), True),
    )


def people_of(entries):
    return [Person(first=r.get("first") or "", last=r.get("last") or "",
                   preferred=r.get("preferred") or "", role=r.get("role") or "")
            for r in entries or ()]


MARK = ""


def shown(scrubbed, mapping, leave):
    """The scrubbed text with the tokens of ``leave`` kinds put back, as a reader sees it."""
    issued = mapping.by_token
    return core.TOKEN.sub(lambda m: issued.get(m.group(0), m.group(0))
                          if m.group("kind") in leave else m.group(0), scrubbed)


def flatten(scrubbed):
    """Each token becomes one private-use character, so the aligner cannot match the
    digits and letters inside a token's hex against the original. Returns the flat text
    and the kind of each mark, in order."""
    kinds = [m.group("kind") for m in core.TOKEN.finditer(scrubbed)]
    return core.TOKEN.sub(MARK, scrubbed), kinds


def survivors(original, scrubbed):
    """For each character of the original, True when it survives in place in the output."""
    flat, _kinds = flatten(scrubbed)
    kept = [False] * len(original)
    matcher = difflib.SequenceMatcher(None, original, flat, autojunk=False)
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            for i in range(i1, i2):
                kept[i] = True
    return kept


_TITLE = re.compile(r"(?i)(?:mr|mrs|ms|miss|mx|dr|prof|sir|dame)\.?[ \t]+(?=\S)")


def occurrences(text, value):
    out, start = [], 0
    while True:
        at = text.find(value, start)
        if at < 0:
            return out
        before = text[at - 1:at]
        after = text[at + len(value):at + len(value) + 1]
        if not (before.isalnum() and value[:1].isalnum()) and \
                not (after.isalnum() and value[-1:].isalnum()):
            out.append(at)
        start = at + 1


def token_spans(original, scrubbed):
    """Spans of the original that a name token took, found by lining the two up."""
    flat, order = flatten(scrubbed)
    marks = [i for i, ch in enumerate(flat) if ch == MARK]
    kind_at = dict(zip(marks, order))
    spans = []
    matcher = difflib.SequenceMatcher(None, original, flat, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace" and i2 > i1:
            kinds = {kind_at[j] for j in range(j1, j2) if j in kind_at}
            if any(core.is_name_kind(k) for k in kinds):
                spans.append((i1, i2))
    return spans


def roster_truth(case, value):
    names = set()
    for r in case.get("roster", ()):
        for part in (r.get("first"), r.get("last"), r.get("preferred")):
            if part:
                names.add(fold(part))
                names.update(fold(w) for w in part.replace("-", " ").split())
        if r.get("first") and r.get("last"):
            names.add(fold(r["first"] + " " + r["last"]))
    words = [fold(w.strip(".,'’")) for w in value.split()]
    return fold(value) in names or all(w in names for w in words if w)


def run(cases, negatives, hush, known=True, unscored=()):
    """Score one configured :class:`hush.Hush` on a test set."""
    stats, by_roster, by_shape = {}, {}, {}
    restore_exact = restore_total = 0
    extra = label_mismatch = 0
    kept_total = kept_intact = 0
    misses, keep_misses = [], []
    leave = {"KEEP", *hush.config.flag}
    packs = hush.config.packs
    for case in cases:
        text = case["text"]
        result = hush.scrub(text, people=people_of(case.get("roster")) if known else (),
                            keep=people_of(case.get("keep")))
        scrubbed, mapping = result.tokens, result.mapping
        restore_total += 1
        if core.restore(scrubbed, mapping) == text:
            restore_exact += 1
        refused = not residual.check(scrubbed, mapping, packs=packs)["clean"]
        view = shown(scrubbed, mapping, leave)
        kept = survivors(text, view)
        covered = [False] * len(text)
        for span in case["spans"]:
            kind, value = span["kind"], span["value"]
            for at in occurrences(text, value):
                for i in range(at, at + len(value)):
                    covered[i] = True
                if kind == "KEEP":
                    kept_total += 1
                    whole = all(kept[i] for i in range(at, at + len(value))
                                if text[i].isalnum())
                    kept_intact += whole
                    if not whole:
                        keep_misses.append((case["id"], value))
                    continue
                if kind in unscored:
                    continue
                row = stats.setdefault(kind, {"occ": 0, "caught": 0, "blocked": 0})
                row["occ"] += 1
                skip = _TITLE.match(value)
                skip = skip.end() if skip else 0
                leaked = any(kept[i] and text[i].isalnum()
                             for i in range(at + skip, at + len(value)))
                if not leaked:
                    row["caught"] += 1
                elif refused:
                    row["blocked"] += 1
                if "on_roster" in span:
                    label = span.get("on_roster") or "no"
                    if (label == "yes") != roster_truth(case, value) and label != "variant":
                        label_mismatch += 1
                    group = by_roster.setdefault(label, {"occ": 0, "caught": 0})
                    group["occ"] += 1
                    group["caught"] += not leaked
                    shape = by_shape.setdefault(case["shape"], {"occ": 0, "caught": 0})
                    shape["occ"] += 1
                    shape["caught"] += not leaked
                    if leaked:
                        misses.append((case["id"], value))
        for s, e in token_spans(text, view):
            if not any(covered[s:e]):
                extra += 1
    fp_cases, fp_spans = 0, 0
    for neg in negatives:
        result = hush.scrub(neg["text"])
        names = [m for m in core.TOKEN.finditer(result.tokens)
                 if core.is_name_kind(m.group("kind"))]
        if names:
            fp_cases += 1
            fp_spans += len(names)
    return {"types": stats, "by_roster": by_roster, "by_shape": by_shape,
            "negatives": len(negatives), "fp_negatives": fp_cases, "fp_names": fp_spans,
            "extra_names": extra, "restore_exact": restore_exact,
            "restore_total": restore_total, "kept_total": kept_total,
            "kept_intact": kept_intact, "roster_label_mismatches": label_mismatch,
            "misses": misses, "keep_misses": keep_misses}


def pct(caught, occ):
    return "%5.1f%%" % (100.0 * caught / occ) if occ else "   n/a"


def run_all(data, config):
    cases, negatives = data["cases"], data.get("negatives", [])
    unscored = tuple(data.get("unscored", ()))
    return {name: run(cases, negatives, Hush(config=config, **options), known, unscored)
            for name, options, known in columns(config)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="the hush bench")
    parser.add_argument("cases", help="a test set in the JSON shape above")
    parser.add_argument("--config", help="a hush config file (TOML or JSON)")
    parser.add_argument("--json", action="store_true", help="print the full results as JSON")
    parser.add_argument("--misses", type=int, default=0,
                        help="print up to N missed names (spans with on_roster) and lost "
                             "kept names for the config's preset")
    args = parser.parse_args(argv)
    config = load(args.config) if args.config else Config()
    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    names = [name for name, _o, _k in columns(config)]
    results = run_all(data, config)
    if args.json:
        print(json.dumps({"cases": data.get("version"), "config": config.name or args.config,
                          "results": results}, indent=1, ensure_ascii=False))
        return 0
    cases, negatives = data["cases"], data.get("negatives", [])
    print("hush bench: %d cases, %d negatives (%s), config: %s"
          % (len(cases), len(negatives), data.get("version"),
             config.name or args.config or "none"))
    print("%-24s" % "kind (occurrences)" + "".join("%18s" % n for n in names))
    first = results[names[0]]
    listed = {s["kind"] for case in cases for s in case["spans"] if "on_roster" in s}
    kinds = sorted(first["types"], key=lambda k: (k not in listed, -first["types"][k]["occ"], k))
    for kind in kinds:
        occ = first["types"][kind]["occ"]
        print("%-24s" % ("%s (%d)" % (kind, occ)) + "".join(
            "%18s" % pct(results[n]["types"][kind]["caught"], occ) for n in names))
    if first["by_roster"]:
        print("names, by the known list:")
        for label in ("yes", "variant", "no"):
            occ = first["by_roster"].get(label, {}).get("occ", 0)
            print("%-24s" % ("  on it: %s (%d)" % (label, occ)) + "".join(
                "%18s" % pct(results[n]["by_roster"].get(label, {}).get("caught", 0), occ)
                for n in names))
    if first["kept_total"]:
        print("%-24s" % ("kept names intact (%d)" % first["kept_total"]) + "".join(
            "%18s" % pct(results[n]["kept_intact"], results[n]["kept_total"]) for n in names))
    print("%-24s" % "negatives with a FP" + "".join(
        "%18s" % ("%d of %d" % (results[n]["fp_negatives"], results[n]["negatives"]))
        for n in names))
    print("%-24s" % "extra names taken" + "".join(
        "%18d" % results[n]["extra_names"] for n in names))
    print("%-24s" % "exact restore" + "".join(
        "%18s" % ("%d of %d" % (results[n]["restore_exact"], results[n]["restore_total"]))
        for n in names))
    preset = names[4]
    if results[preset]["by_shape"]:
        print("names (spans with on_roster) by shape, %s:" % preset)
        print("  " + ", ".join("%s %s" % (s, pct(v["caught"], v["occ"]).strip())
                               for s, v in sorted(results[preset]["by_shape"].items())))
        print("tester's on_roster labels that disagree with the known list: %d"
              % first["roster_label_mismatches"])
    if args.misses:
        print("missed names, %s (case, value):" % preset)
        for case_id, value in results[preset]["misses"][:args.misses]:
            print("  %s %r" % (case_id, value))
        for case_id, value in results[preset]["keep_misses"][:args.misses]:
            print("  kept name lost: %s %r" % (case_id, value))
    return 0


if __name__ == "__main__":
    sys.exit(main())
