"""The command line.

    python3 -m hush presets
    python3 -m hush packs
    python3 -m hush scrub [--config FILE] [--preset share] [--people CSV ...] [--keep FILE ...]
                          [--key-env NAME] [--no-names] [--any-case] [--no-guess] [--json]
                          [FILE]
    python3 -m hush table IN.csv OUT.csv [--config FILE] [--preset dataset]
                          [--people CSV ...] [--key-env NAME]

``scrub`` reads FILE (or standard input) and prints the scrubbed text; a short report of
what was removed, by kind and count, goes to standard error, with what the config flags
for review. It never prints a removed value. When the second check finds something the
preset refuses, nothing is printed and the exit code is 3.

``--people`` is a CSV of known people (or a text file, one name per line) to remove in
all their forms; ``--keep`` is the same for people never to remove. ``--roster`` is the
older name for ``--people``, and ``--staff`` adds people with the role "staff".

``--key-env NAME`` reads the key for pseudonyms and fakes from the environment variable
NAME, so the key never sits on a command line or in a shell history. Without it, codes
are stable within one run only. A config may name the variable with ``key_env``.

Exit codes: 0 done, 2 bad arguments, a bad config or unreadable input, 3 refused.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from hush import core
from hush.config import Config, load
from hush.people import read_names
from hush.presets import PRESETS, Hush


def _key(name):
    if not name:
        return None
    value = os.environ.get(name)
    if not value:
        raise SystemExit("hush: environment variable %s is not set" % name)
    return value.encode("utf-8")


def _read(paths, role, columns):
    people = []
    for path in paths or ():
        people += read_names(path, role, columns=columns)
    return people


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 -m hush",
        description="Find chosen kinds of personal data in a transcript or any text, and "
                    "replace it.")
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("presets", help="list the presets")
    sub.add_parser("packs", help="list the detector packs")
    for verb in ("scrub", "table"):
        p = sub.add_parser(verb)
        p.add_argument("--config", metavar="FILE", help="a config file, TOML or JSON")
        p.add_argument("--preset", choices=sorted(PRESETS),
                       help="default: the config's preset, else %s"
                            % ("share" if verb == "scrub" else "dataset"))
        p.add_argument("--people", "--roster", action="append", metavar="CSV",
                       dest="people",
                       help="known people: First and Last (or Name), and any of Preferred, "
                            "Username, Email, ID, Role; or one name per line; repeatable")
        p.add_argument("--staff", action="append", metavar="CSV",
                       help="known people with the role staff")
        p.add_argument("--keep", action="append", metavar="FILE",
                       help="people never to remove, in the same shape; repeatable")
        p.add_argument("--key-env", metavar="NAME",
                       help="environment variable holding the key for pseudonyms and fakes")
        if verb == "scrub":
            p.add_argument("--no-names", action="store_true", help="no first-name list")
            p.add_argument("--any-case", action="store_true",
                           help="first-name-list names in lower case and capitals too")
            p.add_argument("--no-guess", action="store_true",
                           help="no capitalised-name guess")
            p.add_argument("--json", action="store_true",
                           help="print a JSON object: text, removed, findings, flags, refused")
            p.add_argument("file", nargs="?")
        else:
            p.add_argument("src")
            p.add_argument("dest")
    args = parser.parse_args(argv)

    if args.verb == "presets":
        for preset in PRESETS.values():
            print("%-8s %-9s %s" % (preset.name, preset.style, preset.use))
        return 0
    if args.verb == "packs":
        for name, use in core.PACKS.items():
            print("%-14s %-3s %s" % (name, "on" if name in core.DEFAULT_PACKS else "off", use))
        return 0

    try:
        config = load(args.config) if args.config else Config()
        columns = config.columns
        people = _read(args.people, "", columns)
        staff = _read(args.staff, "staff", columns)
        keep = _read(args.keep, "", columns)
    except (OSError, ValueError, UnicodeDecodeError) as err:
        print("hush: %s" % err, file=sys.stderr)
        return 2
    key = _key(args.key_env or config.key_env)

    if args.verb == "table":
        from hush.tables import scrub_file
        try:
            report = scrub_file(args.src, args.dest, args.preset or config.preset or "dataset",
                                config=config, people=people, staff=staff, key=key)
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
    hush = Hush(args.preset, config=config, people=people, staff=staff, keep=keep, key=key,
                **overrides)
    result = hush.scrub(text)
    if args.json:
        print(json.dumps({"text": result.text, "removed": result.removed,
                          "findings": result.findings, "flags": result.flags,
                          "quasi": result.quasi, "warnings": result.warnings,
                          "refused": result.refused}, indent=1))
    else:
        if not result.refused:
            sys.stdout.write(result.text)
        print("hush %s: removed %s%s" % (
            result.preset.name, json.dumps(result.removed, sort_keys=True),
            "; REFUSED, the second check found %s" % json.dumps(result.findings)
            if result.refused else (
                "; second check found %s" % json.dumps(result.findings)
                if result.findings else "")), file=sys.stderr)
        if result.flags:
            counts = {}
            for flag in result.flags:
                counts[flag["kind"]] = counts.get(flag["kind"], 0) + 1
            print("hush: flagged for review %s (use --json for where)"
                  % json.dumps(counts, sort_keys=True), file=sys.stderr)
        for warned in result.warnings:
            print("hush: warning: %s" % warned, file=sys.stderr)
    if result.preset.reversible and not args.json:
        print("hush: ask-ai tokens only restore inside the same process; use the Python "
              "API (Result.restore) for a round trip", file=sys.stderr)
    return 3 if result.refused else 0


if __name__ == "__main__":
    sys.exit(main())
