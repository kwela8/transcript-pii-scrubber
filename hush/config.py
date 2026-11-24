"""A config file for one use case: which detectors run, who the known people are, which
names to keep, which words are never a name, what is removed and what is only flagged.

TOML (read with the standard library's tomllib) or JSON with the same keys. Paths in the
file are read relative to the file. Every key is optional; ``examples/`` has three
complete configs.

.. code-block:: toml

    preset = "share"                 # ask-ai, share, dataset, demo or logs
    flag = ["DATE"]                  # kinds left in place and listed for review
    check = "refuse"                 # the second check: refuse, warn or off

    [packs]                          # detector packs; a pack not named keeps its default
    general = true
    uk = true
    north-america = false
    south-africa = false

    [names]
    list = true                      # the first-name list
    any_case = true                  # first-name-list names in lower case and capitals
    guess = true                     # the capitalised-name guess
    files = ["more-first-names.txt"] # names to add to the first-name list

    [people]
    known = ["customers.csv"]        # people to remove, with all their forms
    keep = ["agents.txt"]            # names never removed
    role = "customer"                # the role of a known person whose row names none
    columns = { "Account ref" = "id" }   # extra CSV headers and the field they hold
    login_labels = ["member"]        # extra words that label a login

    [words]
    keep = ["Acme", "Hub Two"]       # never a name; a phrase is kept whole
    keep_files = ["products.txt"]

    [[redact]]                       # words and phrases always removed
    kind = "CLIENT"
    label = "client"
    words = ["Northwind Traders"]
    files = []

    [[detectors]]                    # your own patterns, run before the built-in shapes
    kind = "ORDER"
    label = "order"
    pattern = 'ORD-\\d{6}'
    ignore_case = false

    [transcript]
    speakers = "keep"                # text, keep or relabel
    roles = { "Priya Shah" = "agent" }

    [cues]                           # a removed name near one of these gets the role
    child = ["son", "daughter"]
    window = 4

    [labels]                         # what a kind is called in a label
    PERSON_CUSTOMER = "customer"
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from hush import core
from hush.people import Detector, read_names, read_words

_KIND = re.compile(r"[A-Z][A-Z0-9_]{1,31}\Z")
_FIELDS = ("first", "last", "preferred", "full", "username", "email", "id", "role")
_SPEAKERS = ("text", "keep", "relabel")
_TOP = {"name", "description", "preset", "flag", "check", "key_env", "packs", "names",
        "people", "words", "redact", "detectors", "transcript", "cues", "labels"}
_TABLES = {
    "names": {"list", "any_case", "guess", "files"},
    "people": {"known", "keep", "role", "columns", "login_labels"},
    "words": {"keep", "keep_files"},
    "transcript": {"speakers", "roles"},
}


@dataclass
class Config:
    """One use case's settings. Build it with :func:`load`, or directly; every field has
    a default that matches hush with no config."""
    source: Path | None = None
    name: str = ""
    preset: str | None = None
    check: str | None = None
    key_env: str = ""
    packs: tuple = core.DEFAULT_PACKS
    names: bool | None = None
    any_case: bool | None = None
    guess: bool | None = None
    first_names: tuple = ()
    known: list = field(default_factory=list)
    keep: list = field(default_factory=list)
    role: str = "person"
    columns: dict = field(default_factory=dict)
    login_labels: tuple = ()
    keep_words: tuple = ()
    detectors: tuple = ()
    flag: tuple = ()
    labels: dict = field(default_factory=dict)
    speakers: str = "text"
    speaker_roles: dict = field(default_factory=dict)
    cues: dict = field(default_factory=dict)
    cue_window: int = 4


def _list(value, where):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    raise ValueError("hush config: %s must be a string or a list of strings" % where)


def _bool(value, where):
    if value is None or isinstance(value, bool):
        return value
    raise ValueError("hush config: %s must be true or false" % where)


def _kind(value, where):
    if not isinstance(value, str) or not _KIND.match(value):
        raise ValueError("hush config: %s must be a kind in capitals, such as ORDER_REF "
                         "(letters, digits and _, 2 to 32 long)" % where)
    return value


def _table(data, name):
    value = data.get(name) or {}
    if not isinstance(value, dict):
        raise ValueError("hush config: [%s] must be a table" % name)
    unknown = set(value) - _TABLES.get(name, set(value))
    if unknown:
        raise ValueError("hush config: unknown key %s in [%s]; known keys are %s"
                         % (", ".join(sorted(unknown)), name, ", ".join(sorted(_TABLES[name]))))
    return value


def load(path):
    """Read one config file (.toml or .json) and return a :class:`Config`."""
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix.lower() == ".json":
        data = json.loads(raw.decode("utf-8"))
    else:
        import tomllib
        data = tomllib.loads(raw.decode("utf-8"))
    return from_dict(data, base=path.parent, source=path)


def from_dict(data, *, base=".", source=None):
    """A :class:`Config` from a dict with the file's keys. Paths are read from ``base``."""
    from hush.presets import PRESETS
    base = Path(base)
    if not isinstance(data, dict):
        raise ValueError("hush config: the file must hold a table of settings")
    unknown = set(data) - _TOP
    if unknown:
        raise ValueError("hush config: unknown key %s; known keys are %s"
                         % (", ".join(sorted(unknown)), ", ".join(sorted(_TOP))))
    cfg = Config(source=source, name=str(data.get("name") or ""))

    preset = data.get("preset")
    if preset is not None and preset not in PRESETS:
        raise ValueError("hush config: preset must be one of %s" % ", ".join(PRESETS))
    cfg.preset = preset
    check = data.get("check")
    if check is not None and check not in ("refuse", "warn", "off"):
        raise ValueError("hush config: check must be refuse, warn or off")
    cfg.check = check
    cfg.key_env = str(data.get("key_env") or "")
    cfg.flag = tuple(_kind(k, "flag") for k in _list(data.get("flag"), "flag"))

    packs = data.get("packs") or {}
    if not isinstance(packs, dict):
        raise ValueError("hush config: [packs] must be a table of pack = true or false")
    state = {p: p in core.DEFAULT_PACKS for p in core.PACKS}
    for name, on in packs.items():
        if name not in core.PACKS:
            raise ValueError("hush config: unknown pack %s; the packs are %s"
                             % (name, ", ".join(core.PACKS)))
        state[name] = _bool(on, "packs.%s" % name)
    cfg.packs = tuple(p for p in core.PACKS if state[p])

    names = _table(data, "names")
    cfg.names = _bool(names.get("list"), "names.list")
    cfg.any_case = _bool(names.get("any_case"), "names.any_case")
    cfg.guess = _bool(names.get("guess"), "names.guess")
    firsts = []
    for name in _list(names.get("files"), "names.files"):
        firsts += read_words(base / name)
    cfg.first_names = tuple(firsts)

    people = _table(data, "people")
    cfg.role = str(people.get("role") or "person")
    columns = people.get("columns") or {}
    if not isinstance(columns, dict) or any(v not in _FIELDS for v in columns.values()):
        raise ValueError("hush config: people.columns maps a header to one of %s"
                         % ", ".join(_FIELDS))
    cfg.columns = dict(columns)
    cfg.login_labels = tuple(_list(people.get("login_labels"), "people.login_labels"))
    for name in _list(people.get("known"), "people.known"):
        cfg.known += read_names(base / name, columns=cfg.columns)
    for name in _list(people.get("keep"), "people.keep"):
        cfg.keep += read_names(base / name, columns=cfg.columns)

    words = _table(data, "words")
    keep = list(_list(words.get("keep"), "words.keep"))
    for name in _list(words.get("keep_files"), "words.keep_files"):
        keep += read_words(base / name)
    cfg.keep_words = tuple(keep)

    detectors, labels = [], {}
    for i, entry in enumerate(data.get("redact") or []):
        where = "redact[%d]" % i
        if not isinstance(entry, dict) or set(entry) - {"kind", "label", "words", "files"}:
            raise ValueError("hush config: %s takes kind, label, words and files" % where)
        kind = _kind(entry.get("kind", "REDACT"), where + ".kind")
        listed = list(_list(entry.get("words"), where + ".words"))
        for name in _list(entry.get("files"), where + ".files"):
            listed += read_words(base / name)
        detectors.append(Detector.words(kind, listed, str(entry.get("label") or "")))
    for i, entry in enumerate(data.get("detectors") or []):
        where = "detectors[%d]" % i
        if not isinstance(entry, dict) or \
                set(entry) - {"kind", "label", "pattern", "ignore_case", "group"}:
            raise ValueError("hush config: %s takes kind, label, pattern, ignore_case and "
                             "group" % where)
        kind = _kind(entry.get("kind"), where + ".kind")
        try:
            pattern = re.compile(entry.get("pattern") or "",
                                 re.I if entry.get("ignore_case") else 0)
        except re.error as err:
            raise ValueError("hush config: %s.pattern does not compile: %s" % (where, err))
        if not pattern.pattern:
            raise ValueError("hush config: %s needs a pattern" % where)
        detectors.append(Detector(kind, pattern, str(entry.get("label") or ""),
                                  entry.get("group", 0)))
    cfg.detectors = tuple(detectors)

    raw_labels = data.get("labels") or {}
    if not isinstance(raw_labels, dict):
        raise ValueError("hush config: [labels] maps a kind to its label")
    for kind, label in raw_labels.items():
        labels[_kind(kind, "labels")] = str(label)
    cfg.labels = labels

    transcript = _table(data, "transcript")
    speakers = transcript.get("speakers", "text")
    if speakers not in _SPEAKERS:
        raise ValueError("hush config: transcript.speakers must be one of %s"
                         % ", ".join(_SPEAKERS))
    cfg.speakers = speakers
    roles = transcript.get("roles") or {}
    if not isinstance(roles, dict) or not all(isinstance(v, str) for v in roles.values()):
        raise ValueError("hush config: transcript.roles maps a speaker label to a role")
    cfg.speaker_roles = dict(roles)

    cues = dict(data.get("cues") or {})
    window = cues.pop("window", 4)
    if not isinstance(window, int) or window < 1:
        raise ValueError("hush config: cues.window must be a whole number of words")
    cfg.cue_window = window
    cfg.cues = {role: tuple(_list(words, "cues.%s" % role)) for role, words in cues.items()}
    return cfg
