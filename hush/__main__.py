"""The command line.

    python3 -m hush presets
    python3 -m hush scrub [--preset share] [--roster CLASS.csv ...] [--staff STAFF.csv]
                          [--key-env NAME] [--no-names] [--any-case] [--no-guess] [FILE]
    python3 -m hush table IN.csv OUT.csv [--preset dataset] [--roster CLASS.csv ...]
                          [--key-env NAME]

``scrub`` reads FILE (or standard input) and prints the scrubbed text; a short report
of what was removed, by kind and count, goes to standard error. It never prints a removed
value. When the second check finds something the preset refuses, nothing is printed and
the exit code is 3.

``--key-env NAME`` reads the key for pseudonyms and fakes from the environment variable
NAME, so the key never sits on a command line or in a shell history. Without it, codes
are stable within one run only.

Exit codes: 0 done, 2 bad arguments or unreadable input, 3 refused.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from hush.presets import PRESETS, Hush
from hush.students import read_roster


def _key(name):
    if not name:
        return None
    value = os.environ.get(name)
    if not value:
        raise SystemExit("hush: environment variable %s is not set" % name)
    return value.encode("utf-8")


def _people(paths, kind):
    people = []
    for path in paths or ():
        people += read_roster(path, kind=kind)
    return people


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m hush",
                                     description="Find personal data, pupils' names first, "
                                                 "and replace it.")
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("presets", help="list the presets")
    for verb in ("scrub", "table"):
        p = sub.add_parser(verb)
        p.add_argument("--preset", default="share" if verb == "scrub" else "dataset",
                       choices=sorted(PRESETS))
        p.add_argument("--roster", action="append", metavar="CSV",
                       help="a class list: Forename and Surname (or Name), and any of "
                            "Preferred, Username, Email, UPN, ULN; repeatable")
        p.add_argument("--staff", action="append", metavar="CSV", help="a staff list")
        p.add_argument("--key-env", metavar="NAME",
                       help="environment variable holding the key for pseudonyms and fakes")
        if verb == "scrub":
            p.add_argument("--no-names", action="store_true", help="no first-name list")
            p.add_argument("--any-case", action="store_true",
                           help="first-name-list names in lower case and capitals too")
            p.add_argument("--no-guess", action="store_true",
                           help="no capitalised-name guess")
            p.add_argument("--json", action="store_true",
                           help="print a JSON object: text, removed, findings, refused")
            p.add_argument("file", nargs="?")
        else:
            p.add_argument("src")
            p.add_argument("dest")
    args = parser.parse_args(argv)

    if args.verb == "presets":
        for preset in PRESETS.values():
            print("%-8s %-9s %s" % (preset.name, preset.style, preset.use))
        return 0

    try:
        roster = _people(args.roster, "STUDENT")
        staff = _people(args.staff, "STAFF")
    except (OSError, ValueError) as err:
        print("hush: %s" % err, file=sys.stderr)
        return 2
    key = _key(args.key_env)

    if args.verb == "table":
        from hush.tables import scrub_file
        try:
            report = scrub_file(args.src, args.dest, args.preset, roster=roster, staff=staff,
                                key=key)
        except (OSError, UnicodeDecodeError) as err:
            print("hush: %s" % err, file=sys.stderr)
            return 2
        print(json.dumps(report, indent=1), file=sys.stderr)
        return 0

    overrides = {}
    if args.no_names:
        overrides["names"] = False
    if args.any_case:
        overrides["any_case"] = True
    if args.no_guess:
        overrides["guess"] = False
    try:
        text = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    except (OSError, UnicodeDecodeError) as err:
        print("hush: %s" % err, file=sys.stderr)
        return 2
    result = Hush(args.preset, roster=roster, staff=staff, key=key, **overrides).scrub(text)
    if args.json:
        print(json.dumps({"text": result.text, "removed": result.removed,
                          "findings": result.findings, "refused": result.refused}, indent=1))
    else:
        if not result.refused:
            sys.stdout.write(result.text)
        print("hush %s: removed %s%s" % (
            result.preset.name, json.dumps(result.removed, sort_keys=True),
            "; REFUSED, the second check found %s" % json.dumps(result.findings)
            if result.refused else (
                "; second check found %s" % json.dumps(result.findings)
                if result.findings else "")), file=sys.stderr)
    if result.preset.reversible and not args.json:
        print("hush: ask-ai tokens only restore inside the same process; use the Python "
              "API (Result.restore) for a round trip", file=sys.stderr)
    return 3 if result.refused else 0


if __name__ == "__main__":
    sys.exit(main())
