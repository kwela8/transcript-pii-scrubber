"""Build hush's first-name lists from the ONS baby names workbook and an English word list.

    python3 tools/build_names.py ONS.xlsx WORDS.txt OUT_DIR [--min-count N]

ONS.xlsx is "Baby names in England and Wales: 1996 to 2025" (Office for National
Statistics, Open Government Licence v3.0): every first name given to 3 or more babies in
a year, girls in Table_1 and boys in Table_2. WORDS.txt is a plain word list, one word per
line, in which proper nouns keep their capital (Debian's wbritish, SCOWL). Needs openpyxl.

Writes three files to OUT_DIR, one entry per line, sorted:

- common_first_names.txt: names given to 1,000 babies or more over the years, spelled as
  registered, each with g, b or x (girls four times as often as boys, the reverse, or
  neither), for the fake style's made-up names.
- name_sex.txt: every kept name that is clearly a girl's (g) or a boy's (b) name by the
  same four-to-one rule, so a fake can keep the sex of the name it replaces.
- words.txt: the word list's lower-case words, so a detector can tell "Brathwaite has"
  (a name) from "Homework has" (a word) at the start of a sentence.

- first_names.txt: names whose lower-case form is not an English word ("Aisha",
  "Jayden"). A detector may take these wherever they appear, in any case.
- name_words.txt: names whose lower-case form is an English word ("Grace", "Will",
  "Summer"). A detector should take these only with a capital and only where a name fits.

A name is kept when its count over all years is at least --min-count (default 10). The
count is summed over every year column, so a name common in 2005 and rare now stays.
Names of one letter, and entries with anything but letters, hyphens and apostrophes, are
left out.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

NAME = re.compile(r"[^\W\d_](?:[^\W\d_]|['’-](?=[^\W\d_]))+\Z")


def read_ons(path, by_sex=None):
    """{name: total} over both tables; ``by_sex``, when given a dict, is filled with
    {name: {"g": girls' total, "b": boys' total}}."""
    import openpyxl
    totals = {}
    book = openpyxl.load_workbook(path, read_only=True)
    for sheet, sex in (("Table_1", "g"), ("Table_2", "b")):
        rows = book[sheet].iter_rows(values_only=True)
        header = None
        for row in rows:
            if row and row[0] == "Name":
                header = row
                break
        if header is None:
            raise SystemExit("build_names: no Name header in %s" % sheet)
        counts = [i for i, h in enumerate(header) if isinstance(h, str) and h.endswith("Count")]
        for row in rows:
            name = row[0]
            if not isinstance(name, str):
                continue
            total = sum(row[i] for i in counts if isinstance(row[i], (int, float)))
            totals[name.strip()] = totals.get(name.strip(), 0) + int(total)
            if by_sex is not None:
                by_sex.setdefault(name.strip(), {"g": 0, "b": 0})[sex] += int(total)
    return totals


def read_words(path):
    lower = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and word[0].islower():
            lower.add(word.lower())
    return lower


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ons")
    parser.add_argument("words")
    parser.add_argument("out")
    parser.add_argument("--min-count", type=int, default=10)
    args = parser.parse_args(argv)
    by_sex = {}
    totals = read_ons(args.ons, by_sex)
    words = read_words(args.words)
    plain, wordy = set(), set()
    for name, total in totals.items():
        if total < args.min_count or not NAME.match(name):
            continue
        (wordy if name.lower() in words else plain).add(name)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "first_names.txt").write_text("\n".join(sorted(plain)) + "\n", encoding="utf-8")
    (out / "name_words.txt").write_text("\n".join(sorted(wordy)) + "\n", encoding="utf-8")
    def sex(name):
        g, b = by_sex[name]["g"], by_sex[name]["b"]
        return "g" if g >= 4 * b else "b" if b >= 4 * g else "x"

    common = sorted(n for n, t in totals.items() if t >= 1000 and NAME.match(n) and "-" not in n)
    (out / "common_first_names.txt").write_text(
        "".join("%s\t%s\n" % (n, sex(n)) for n in common), encoding="utf-8")
    kept = sorted(plain | wordy, key=str.lower)
    (out / "name_sex.txt").write_text(
        "".join("%s\t%s\n" % (n, sex(n)) for n in kept if sex(n) != "x"), encoding="utf-8")
    plain_words = sorted(w for w in words if NAME.match(w) and "'" not in w)
    (out / "words.txt").write_text("\n".join(plain_words) + "\n", encoding="utf-8")
    print("build_names: %d names read, %d kept as names, %d kept as name-words (min count %d); "
          "%d lower-case words" % (len(totals), len(plain), len(wordy), args.min_count,
                                   len(plain_words)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
