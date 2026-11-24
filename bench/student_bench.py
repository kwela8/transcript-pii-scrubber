"""The pupil-names bench: how many names and identifiers get through, set by set.

    python3 bench/student_bench.py [CASES.json] [--json]

The cases (bench/student_cases.json, 150 texts and 40 negatives) were written by a
separate tester who never saw this code: teacher and parent emails, support notes, chat,
CSV, TSV and JSON exports, logs, report comments, SEN notes, OCR'd class lists. Each
case lists its sensitive values and the class list the school would hold.

How a value is scored. The text is scrubbed into tokens; each occurrence of a listed value
is lined up with the output character by character (difflib). It is **caught** when none
of its letters or digits survive where it stood, so taking "Aisha" and leaving "Khan"
from "Aisha Khan" is a miss. Recall is caught occurrences over occurrences.

A negative is a **false positive** when a name kind (PERSON, STUDENT, STAFF, CLINICIAN,
PLACE) takes anything from it. Dates, codes and long numbers are taken by policy and do
not count. **Extra names** counts, over the positive cases, the name tokens that cover no
listed value: words wrongly taken as names, or names the tester did not list.

The configurations run from "the core alone" (what hush did before the pupils layer) up
to the ``share`` preset with the class list. ``restore`` checks that every token-style
scrub restores to the original text exactly.
"""
from __future__ import annotations

import argparse
import difflib
import re
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hush import core, residual  # noqa: E402
from hush.students import Person, Pupils, fold, keep_guess  # noqa: E402

NAME_KINDS = {"PERSON", "STUDENT", "STAFF", "CLINICIAN", "PLACE"}
SCORED = ("STUDENT", "ADULT", "USERNAME", "EMAIL", "PHONE", "UPN", "ULN", "DOB", "ADDRESS",
          "POSTCODE")
REPORTED = ("SCHOOL",)

CONFIGS = (
    ("core alone", dict(roster=False, names=False, any_case=False, guess=True)),
    ("+ first-name list", dict(roster=False, names=True, any_case=False, guess=True)),
    ("+ list, any case", dict(roster=False, names=True, any_case=True, guess=True)),
    ("+ class list", dict(roster=True, names=True, any_case=False, guess=True)),
    ("share preset", dict(roster=True, names=True, any_case=True, guess=True)),
    ("logs preset", dict(roster=True, names=True, any_case=True, guess=False)),
)


def roster_of(case):
    return [Person(first=r.get("first") or "", last=r.get("last") or "",
                   preferred=r.get("preferred") or "") for r in case.get("roster", ())]


def scrub(text, case, cfg):
    detector, keep = None, None
    if cfg["roster"] or cfg["names"]:
        pupils = Pupils(roster_of(case) if cfg["roster"] else (), names=cfg["names"],
                        any_case=cfg["any_case"])
        detector, keep = pupils.detector, keep_guess
    return core.scrub(text, students=detector, heuristic_names=cfg["guess"],
                      guess_filter=keep)


MARK = ""


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


def token_spans(original, scrubbed, mapping):
    """Spans of the original that a name token took, found by lining the two up."""
    flat, order = flatten(scrubbed)
    marks = [i for i, ch in enumerate(flat) if ch == MARK]
    kind_at = dict(zip(marks, order))
    spans = []
    matcher = difflib.SequenceMatcher(None, original, flat, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace" and i2 > i1:
            kinds = {kind_at[j] for j in range(j1, j2) if j in kind_at}
            if kinds & NAME_KINDS:
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


def run(cases, negatives, cfg):
    stats = {k: {"occ": 0, "caught": 0, "blocked": 0} for k in SCORED + REPORTED}
    by_roster = {k: {"occ": 0, "caught": 0} for k in ("yes", "variant", "no")}
    by_shape = {}
    restore_exact = restore_total = 0
    extra = 0
    label_mismatch = 0
    misses = []
    for case in cases:
        text = case["text"]
        scrubbed, mapping = scrub(text, case, cfg)
        restore_total += 1
        if core.restore(scrubbed, mapping) == text:
            restore_exact += 1
        refused = not residual.check(scrubbed, mapping)["clean"]
        kept = survivors(text, scrubbed)
        covered = [False] * len(text)
        for span in case["spans"]:
            kind, value = span["kind"], span["value"]
            for at in occurrences(text, value):
                for i in range(at, at + len(value)):
                    covered[i] = True
                if kind not in stats:
                    continue
                stats[kind]["occ"] += 1
                # A title kept in front of a name ("Mrs [person 1]") names no one.
                skip = _TITLE.match(value)
                skip = skip.end() if skip else 0
                leaked = any(kept[i] and text[i].isalnum()
                             for i in range(at + skip, at + len(value)))
                if not leaked:
                    stats[kind]["caught"] += 1
                elif refused:
                    stats[kind]["blocked"] += 1
                if kind == "STUDENT":
                    label = span.get("on_roster", "no")
                    if (label == "yes") != roster_truth(case, value) and label != "variant":
                        label_mismatch += 1
                    row = by_roster.setdefault(label, {"occ": 0, "caught": 0})
                    row["occ"] += 1
                    row["caught"] += not leaked
                    shape = by_shape.setdefault(case["shape"], {"occ": 0, "caught": 0})
                    shape["occ"] += 1
                    shape["caught"] += not leaked
                    if leaked:
                        misses.append((case["id"], value))
        for s, e in token_spans(text, scrubbed, mapping):
            if not any(covered[s:e]):
                extra += 1
    fp_cases, fp_spans = 0, 0
    for neg in negatives:
        scrubbed, mapping = scrub(neg["text"], {"roster": ()}, cfg)
        names = [m for m in core.TOKEN.finditer(scrubbed) if m.group("kind") in NAME_KINDS]
        if names:
            fp_cases += 1
            fp_spans += len(names)
    return {"types": stats, "student_by_roster": by_roster, "student_by_shape": by_shape,
            "negatives": len(negatives), "fp_negatives": fp_cases, "fp_names": fp_spans,
            "extra_names": extra, "restore_exact": restore_exact,
            "restore_total": restore_total, "roster_label_mismatches": label_mismatch,
            "student_misses": misses}


def pct(caught, occ):
    return "%5.1f%%" % (100.0 * caught / occ) if occ else "   n/a"


def main(argv=None):
    parser = argparse.ArgumentParser(description="the pupil-names bench")
    parser.add_argument("cases", nargs="?", default=str(HERE / "student_cases.json"))
    parser.add_argument("--json", action="store_true", help="print the full results as JSON")
    parser.add_argument("--misses", type=int, default=0,
                        help="print up to N missed pupil names for the share preset")
    args = parser.parse_args(argv)
    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases, negatives = data["cases"], data.get("negatives", [])
    results = {name: run(cases, negatives, cfg) for name, cfg in CONFIGS}
    if args.json:
        print(json.dumps({"cases": data.get("version"), "results": results}, indent=1,
                         ensure_ascii=False))
        return 0
    print("pupil-names bench: %d cases, %d negatives (%s)"
          % (len(cases), len(negatives), data.get("version")))
    head = "%-20s" % "kind (occurrences)"
    print(head + "".join("%18s" % name for name, _ in CONFIGS))
    first = results[CONFIGS[0][0]]
    for kind in SCORED:
        occ = first["types"][kind]["occ"]
        if not occ:
            continue
        print("%-20s" % ("%s (%d)" % (kind, occ)) + "".join(
            "%18s" % pct(results[n]["types"][kind]["caught"], occ) for n, _ in CONFIGS))
    print("pupils, by class list:")
    for label in ("yes", "variant", "no"):
        occ = first["student_by_roster"].get(label, {}).get("occ", 0)
        print("%-20s" % ("  on it: %s (%d)" % (label, occ)) + "".join(
            "%18s" % pct(results[n]["student_by_roster"][label]["caught"], occ)
            for n, _ in CONFIGS))
    print("%-20s" % "negatives with a FP" + "".join(
        "%18s" % ("%d of %d" % (results[n]["fp_negatives"], results[n]["negatives"]))
        for n, _ in CONFIGS))
    print("%-20s" % "extra names taken" + "".join(
        "%18d" % results[n]["extra_names"] for n, _ in CONFIGS))
    print("%-20s" % "exact restore" + "".join(
        "%18s" % ("%d of %d" % (results[n]["restore_exact"], results[n]["restore_total"]))
        for n, _ in CONFIGS))
    print("pupil names by shape, share preset:")
    share = results["share preset"]["student_by_shape"]
    print("  " + ", ".join("%s %s" % (s, pct(v["caught"], v["occ"]).strip())
                           for s, v in sorted(share.items())))
    print("tester's on-roster labels that disagree with the class list: %d"
          % first["roster_label_mismatches"])
    if args.misses:
        print("missed pupil names, share preset (case, value):")
        for case_id, value in results["share preset"]["student_misses"][:args.misses]:
            print("  %s %r" % (case_id, value))
    return 0


if __name__ == "__main__":
    sys.exit(main())
