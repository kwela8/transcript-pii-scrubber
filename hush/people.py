"""People's names: the known-people list first, a first-name list second, the core's guess last.

Why this order. A name the scrubber has been told about is matched exactly, in any order
and any case; a name it has not been told about has to be guessed from context, and
guesses miss. An organisation usually holds a list of the people its text is about
(customers, staff, members, a class), so that list does most of the work, and the rest of
this module is for the names it does not cover.

What it takes, and with what kind:

- **Known people** (``Person`` rows, usually read from a CSV with :func:`read_people`):
  every full name in four orders ("Aisha Khan", "Khan, Aisha", "Khan Aisha", a preferred
  name with the surname), each first, preferred and last name alone, possessives, and the
  person's usernames, emails and IDs. The kind follows the role: PERSON, or PERSON_ and
  the role ("PERSON_CUSTOMER", labelled "[customer 1]"). Identifiers keep their own kind
  (USERNAME, EMAIL, ID, or the kind of the caller's detector that matches the value).
- **Names to keep** (the agent on a call, the person a letter is from) are never
  redacted. They are coded as KEEP tokens before any other name rule runs, and put back as
  written when the text is rendered.
- **The first-name list** (``lists/first_names.txt``, from the ONS baby names for England
  and Wales, 1996 to 2025, plus any lists the caller adds): a name there is taken with a
  capital anywhere, including at the start of a sentence, where the core's guess leaves a
  single word alone. With ``any_case=True`` it is also taken in lower case or capitals
  ("jayden", "JAYDEN"). Kind PERSON.
- **Name-words** ("Grace", "Will", "Summer", "Mark": ``lists/name_words.txt``, names whose
  lower-case form is an English word) need care. Known ones are taken only with a
  capital, never after "the", "a", "this" and the like, never before "Scheme", "Term",
  "Period" and the like, and at the start of a sentence only when the next word reads as
  something a person does ("Grace has", "Will is", "Hope's"). Off the list they are left
  to the core's guess. In lower case a known name-word is taken only before such a verb
  or as a possessive ("grace hasn't", "grace's").
- **The caller's own detectors** (:class:`Detector`): a regular expression or a word list
  with a kind, found alongside logins and handles, before the core's shapes.

Words the caller protects (``KEEP`` and its own ``keep_words``) are never taken from the
first-name list, so "Pascal's triangle" survives when "pascal" is a kept word; a person
called Pascal is still taken when Pascal is on the known list.

Accents: every known name also goes in without its accents, so "Zoe" finds "Zoë".
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from hush import core
from hush.core import fold

DATA = Path(__file__).resolve().parent / "lists"

#: Lower-case words that may follow a name-word at the start of a sentence when it is a
#: person ("Grace has", "Will is"). Anything else there and it is read as a word.
SUBJECT_NEXT = {
    "is", "was", "has", "had", "isn't", "wasn't", "hasn't", "hadn't", "isnt", "wasnt",
    "hasnt", "did", "didn't", "didnt", "does", "doesn't", "doesnt", "do", "can", "can't",
    "cant", "could", "couldn't", "will", "won't", "would", "wouldn't", "should", "shouldn't",
    "must", "might", "needs", "need", "got", "gets", "said", "says", "told", "asked", "asks",
    "wants", "went", "came", "left", "joined", "completed", "completes", "finished",
    "scored", "struggled", "struggles", "missed", "misses", "forgot", "forgets", "logged",
    "logs", "lost", "found", "tried", "tries", "worked", "works", "answered", "answers",
    "and", "or", "&", "also", "still", "never", "always", "just", "only", "now", "really",
    "seems", "seemed", "looks", "looked", "managed", "made", "makes", "took", "takes",
    "used", "uses", "submitted", "submits", "uploaded", "started", "starts", "moved",
    "showed", "shows", "keeps", "kept", "reached", "reaches", "earned", "earns", "gained",
}

#: A name-word before one of these is part of a phrase ("Mark Scheme", "Summer Term").
BLOCK_NEXT = {
    "scheme", "schemes", "term", "terms", "period", "periods", "holiday", "holidays",
    "school", "schools", "academy", "college", "camp", "fair", "house", "hall", "street",
    "road", "lane", "avenue", "close", "way", "drive", "park", "garden", "gardens", "group",
    "set", "band", "team", "club", "tree", "trees", "day", "days", "week", "festival",
    "ball", "concert", "show", "sale", "card", "cards", "sheet", "book", "books",
    "project", "break", "fete", "trip", "uniform", "time", "reading", "list", "you", "we",
    "they", "i", "he", "she", "it", "there", "this", "that", "these", "those", "the", "a",
    "an", "your", "our", "my", "be", "of", "in", "on", "at", "for", "to", "up", "down",
    "out", "off", "over", "by", "with", "from", "into", "if", "not", "so", "all", "any",
}

#: A name-word after one of these is a word ("the Summer", "a Will", "next Spring").
BLOCK_BEFORE = {
    "the", "a", "an", "this", "that", "these", "those", "next", "last", "every", "each",
    "our", "your", "my", "his", "her", "their", "its", "some", "any", "no", "of", "in",
    "per", "with", "full", "half", "red", "blue", "green", "gold", "golden",
}

#: Lower-case surname particles that join a capitalised surname ("van der Berg").
PARTICLES = {"van", "der", "den", "von", "de", "da", "di", "del", "della", "du", "le", "la",
             "al", "el", "bin", "binti", "ibn", "ben", "ap", "mac", "mc", "st", "st."}

_WORD = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")

# A title, then up to three name words: capitalised, in capitals, or an initial, with
# surname particles between. "Mrs Pemberton", "Mr J. Okafor", "Dr van der Berg".
# Letters for a capitalised name: every upper- and lower-case Latin, Greek and Cyrillic
# letter (``core._U``, ``core._L``), so "Şahin", "İnce" and "Đặng" read as "Smith" does.
# A part may open with a letter and an apostrophe ("O'Brien") and hold inner capitals
# ("McDonald"); parts join with a hyphen ("Kowalska-Łącka").
_UP, _LO = core._U, core._L
_ONE_PART = (r"(?:[" + _UP + r"]['’])?[" + _UP + r"][" + _LO + r"]+(?:[" + _UP + r"][" + _LO
             + r"]+)*")
_NAME_PART = _ONE_PART + r"(?:-" + _ONE_PART + r")*"
_CAPS_PART = r"[" + _UP + r"]{2,}(?:['’\-][" + _UP + r"]+)*"
_CAP = r"(?:" + _NAME_PART + r"|" + _CAPS_PART + r"|[" + _UP + r"]\.?)"
_PARTICLE = r"(?:van|von|der|den|de|da|di|du|le|la|al|el|bin|ibn)[ \t]+"
_TITLED = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Sir|Dame|MR|MRS|MS|MISS|MX|DR)\.?[ \t]+"
    r"(?P<name>(?:" + _PARTICLE + r")*" + _CAP + r"(?:[ \t]+(?:" + _PARTICLE + r")*"
    r"(?:" + _NAME_PART + r"|" + _CAPS_PART + r")){0,2})"
    r"(?<![" + _UP + r"]\.)(?!['’][a-z]{2,})(?![" + _UP + _LO + r"])")
# An @handle, whole, so no name rule takes the name inside it; and a chat speaker at the
# start of a line, with an optional [time], shaped like a login: lower case with a dot or
# an underscore, or letters then digits ("ms_bell:", "sam.k:", "jdoe23:").
SLACK_KEYWORDS = {"here", "channel", "everyone"}
_HANDLE_AT = re.compile(r"(?<![\w@.])@(?P<h>[A-Za-z0-9_][A-Za-z0-9_.]{0,30}[A-Za-z0-9_])")
_SPEAKER = re.compile(r"(?m)^[ \t>]*(?:\[[0-9:. ]+(?:[AaPp][Mm])?\][ \t]*)?"
                      r"(?P<s>[a-z][a-z0-9]*[._][a-z0-9._]*[a-z0-9]|[a-z]{2,}\d{1,4})(?=:[ \t])")
#: Words that label a login, as regular expressions. A config adds its own ("member").
LOGIN_LABELS = (r"user(?:[ _-]?name)?", r"login", r"log-in", r"uid")
# A login shape: a lower-case name and an initial or a surname after a dot or an
# underscore ("ella.w", "mo_khan"), or a name, up to two letters and a few digits
# ("amberk3"). The head must be a name for it to count.
_USER_SHAPED = re.compile(
    r"(?<![\w.@/\\-])(?P<head>[a-z][a-z'\-]{1,30})"
    r"(?:[._](?P<tail>[a-z0-9]{1,20}(?:[._-][a-z0-9]{1,20})?)|[a-z]{0,2}\d{1,4})"
    r"(?![\w@]|\.[a-z])")
# Words straight after a title that are not a name: "Mr Men", "Miss Out".
_NOT_AFTER_TITLE = {"and", "or", "the", "a", "an", "out", "men", "says", "said"}
_POSSESSIVE = re.compile(r"['’]s\Z", re.I)
# What may come straight before the first word of a sentence, a line, a cell or a quote.
# A comma counts only with no space after it: "9X,Grace,Khan" is a cell, ", Grace" is not.
_STARTS = re.compile(r"(?:[.!?:;]\s+|[\n\t\"“(\[|]\s*|,)\Z")
_SPLIT = re.compile(r"[;|]")


@lru_cache(maxsize=8)
def _user_labelled(extra):
    """A login label and its value: "username: ella.w", "**User Name:** Layla2025", "the
    user name was mickeyberman", "user name associated with this request was lovro_b",
    "the user w.anderson". ``sep`` is the colon, "is" or "was", or empty."""
    labels = list(LOGIN_LABELS) + [re.escape(w) for w in extra]
    return re.compile(
        r"(?i)\b(?:" + "|".join(labels) + r")(?![\w-])[\"']?\**"
        r"(?:[ \t]+(?:associated[ \t]+with|on|for|of|in)(?:[ \t]+[\w-]+){1,3}?"
        r"(?=[ \t]+(?:is|was)\b))?"
        r"[ \t]*(?P<sep>[:=]|\b(?:is|was)\b|,)?\**[ \t]*[\"']?"
        r"(?<=[\s:=,\"'*])(?P<u>[A-Za-z][\w.'\-]{1,40})")


# Shapes of a login built from a name, each needing a name from the lists: a first name
# and digits ("Samuel1995"), two names joined by a dot ("Nimali.Sivagnanam"), joined in
# capitals ("SomchaiHoang") or joined by underscores ("Brent_ShadowHunter"). An initial,
# a dot and a word that is not English is a login with no list ("k.williams"). Names run
# together in lower case ("jbenoit") are not taken: tried, a word list cannot tell them
# from ordinary words it lacks.
_NAME_DIGITS = re.compile(r"(?<![\w@.])(?P<head>[A-Z][a-z]{2,20})\d{2,4}(?![\w@])")
_NAME_DOT_NAME = re.compile(
    r"(?<![\w@./])(?P<head>[A-Z][a-z]{1,20})\.[A-Z][a-z]{1,30}(?![\w@]|\.[A-Za-z])")
_CAMEL_NAMES = re.compile(
    r"(?<![\w@.])(?P<head>[A-Z][a-z]{2,15})[A-Z][a-z]{2,15}(?:[A-Z][a-z]*)*\d{0,4}(?![\w@])")
_UNDERSCORED = re.compile(r"(?<![\w@.])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![\w@])")
_INITIAL_DOT = re.compile(r"(?<![\w@./-])[a-z]\.(?P<tail>[a-z]{3,30})(?![\w@-]|\.[a-z])")
_FILE_ENDINGS = {"com", "org", "net", "txt", "exe", "out", "csv", "pdf", "png", "jpg", "jpeg",
                 "html", "json", "docx", "xlsx", "pptx", "log", "bak", "tmp", "yaml", "toml",
                 "conf", "gif", "svg", "zip", "md", "py", "js", "css"}
# A speaker in lower case that is not a word: "pmarler: Sure."
_SPEAKER_WORD = re.compile(r"(?m)^[ \t>]*(?:\[[0-9:. ]+(?:[AaPp][Mm])?\][ \t]*)?"
                           r"(?P<s>[a-z]{5,20})(?=:[ \t])")


def _at_start(text, start):
    return start == 0 or bool(_STARTS.search(text[max(0, start - 6):start]))


@lru_cache(maxsize=8)
def _load(name):
    path = DATA / name
    if not path.exists():
        return frozenset()
    return frozenset(fold(line.strip()) for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip())


def first_names():
    """Folded first names that are not English words (lists/first_names.txt)."""
    return _load("first_names.txt")


def name_words():
    """Folded first names that are also English words (lists/name_words.txt)."""
    return _load("name_words.txt")


@lru_cache(maxsize=1)
def common_names():
    """Folded first names given to 1,000 babies or more (lists/common_first_names.txt)."""
    path = DATA / "common_first_names.txt"
    if not path.exists():
        return frozenset()
    return frozenset(fold(line.partition("\t")[0]) for line in
                     path.read_text(encoding="utf-8").splitlines() if line.strip())


def english_words():
    """Lower-case English words (lists/words.txt), to tell "Brathwaite has" from "Homework has"."""
    return _load("words.txt")


def read_words(path):
    """The entries of a word file: one per line, blank lines and lines that start with "#"
    left out. A CSV's first column is read the same way."""
    out = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            out.append(entry)
    return out


def split_names(names):
    """``(plain, wordy)``: folded names that are not English words, and those that are."""
    plain, wordy = set(), set()
    for name in names:
        folded = fold(name.strip())
        if folded:
            (wordy if folded in english_words() else plain).add(folded)
    return frozenset(plain), frozenset(wordy)


def table_people(text, columns=None):
    """People in a table pasted into the text: a header row that names a name column
    (Forename, Surname, first_name, Name...) split by tabs, commas, semicolons or bars,
    and the rows under it until a blank line. An export carries its own list of people.
    ``columns`` maps extra headers to fields (see :func:`column_role`)."""
    people = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        found = False
        for delim in ("\t", ",", ";", "|"):
            if delim not in lines[i]:
                continue
            header = [c.strip().strip("*") for c in next(csv.reader([lines[i]], delimiter=delim))]
            roles = [column_role(c, columns) if c else None for c in header]
            if len(header) < 2 or not any(r in ("first", "last", "full") for r in roles):
                continue
            j = i + 1
            while j < len(lines) and lines[j].strip():
                row = [c.strip() for c in next(csv.reader([lines[j]], delimiter=delim))]
                if len(row) < 2:
                    break
                if all(set(c) <= set("-: ") for c in row):      # a Markdown rule
                    j += 1
                    continue
                cells = {}
                for role, value in zip(roles, row):
                    if role and value:
                        cells[role] = value
                person = _person_from(cells)
                if person:
                    people.append(person)
                j += 1
            i, found = j, True
            break
        if not found:
            i += 1
    return people


@dataclass(frozen=True)
class Person:
    """One known person. ``preferred``, ``username``, ``email`` and ``id`` may each hold
    several values split by ";" or "|". ``role`` names what the person is to the text
    ("customer", "staff"); empty means the list's default role."""
    first: str = ""
    last: str = ""
    preferred: str = ""
    username: str = ""
    email: str = ""
    id: str = ""
    role: str = ""

    @property
    def key(self):
        """One string per person, for keyed pseudonyms: the folded legal name."""
        return fold(" ".join(p for p in (self.first, self.last) if p))

    def values(self, name):
        """The values of one field, split on ";" and "|"."""
        return [v.strip() for v in _SPLIT.split(getattr(self, name) or "") if v.strip()]

    @classmethod
    def from_name(cls, name, role=""):
        """A person from a name as written: "Aisha Khan" or "Khan, Aisha"."""
        first, last = split_full(name)
        return cls(first=first, last=last, role=role)


#: Column names a list of people uses, folded and with spaces and dashes as "_".
COLUMNS = {
    "first": {"first", "first_name", "firstname", "forename", "forenames", "given_name",
              "given", "legal_forename", "legal_first_name", "first_names"},
    "last": {"last", "last_name", "lastname", "surname", "family_name", "legal_surname",
             "legal_last_name"},
    "preferred": {"preferred", "preferred_name", "preferred_forename", "known_as",
                  "nickname", "nicknames", "chosen_name", "preferred_first_name"},
    "full": {"name", "full_name", "fullname", "child", "child_name", "display_name"},
    "username": {"username", "usernames", "user_name", "login", "user", "user_id"},
    "email": {"email", "emails", "e_mail", "email_address"},
    "id": {"id", "ids", "identifier"},
    "role": {"role"},
}
_FIELDS = ("first", "last", "preferred", "username", "email", "id", "role")


def _column_key(header):
    return re.sub(r"[\s\-]+", "_", fold(header.strip()))


def column_role(header, columns=None):
    """The field a column holds (first, last, preferred, full, username, email, id or
    role), or None. ``columns`` maps extra headers to fields and is read first."""
    key = _column_key(header)
    for extra, role in (columns or {}).items():
        if _column_key(extra) == key:
            return role
    for role, names in COLUMNS.items():
        if key in names:
            return role
    return None


def split_full(full):
    """``(first, last)`` from a whole name: "Aisha Khan", "Khan, Aisha", "Mary Jane Ellis"."""
    full = " ".join(full.split())
    if "," in full:
        last, _, first = full.partition(",")
        return first.strip(), last.strip()
    parts = full.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


_MANY = ("preferred", "username", "email", "id")


def _person_from(cells, role=""):
    """A Person from {field: value}, or None when no name is given."""
    got = {name: value.strip() for name, value in cells.items() if name and value.strip()}
    if "full" in got and not ("first" in got or "last" in got):
        got["first"], got["last"] = split_full(got.pop("full"))
    got.pop("full", None)
    if not (got.get("first") or got.get("last")):
        return None
    if role and not got.get("role"):
        got["role"] = role
    return Person(**{k: v for k, v in got.items() if k in _FIELDS})


def read_people(path, role="", *, columns=None, kind=None):
    """People from a CSV with a header row. Columns are found by name (``COLUMNS``):
    Forename and Surname, or a single Name ("Aisha Khan" or "Khan, Aisha"), and any of
    preferred name, username, email, ID and role. ``columns`` maps extra headers to those
    fields ({"Customer ref": "id"}). Other columns are ignored. ``role`` is given to every
    row with no role of its own. ``kind`` is the older way to say ``role``."""
    if kind and not role:
        role = kind.lower()
    people = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        roles = {h: column_role(h, columns) for h in (reader.fieldnames or ())}
        if not any(r in ("first", "last", "full") for r in roles.values()):
            raise ValueError("hush: %s has no name column (Forename, Surname or Name)" % path)
        for row in reader:
            cells = {}
            for header, name in roles.items():
                if name and (row.get(header) or "").strip():
                    value = row[header].strip()
                    # Two ID or email columns both count; for a name the last one wins.
                    cells[name] = cells[name] + ";" + value if name in cells and name in _MANY \
                        else value
            person = _person_from(cells, role)
            if person:
                people.append(person)
    return people


#: The older name of :func:`read_people`.
read_roster = read_people


def read_names(path, role="", *, columns=None):
    """People from a file: a CSV read by :func:`read_people` (``.csv``), or a text file
    with one name per line ("Priya Shah" or "Shah, Priya")."""
    if Path(path).suffix.lower() in (".csv", ".tsv"):
        return read_people(path, role, columns=columns)
    return [Person.from_name(name, role) for name in read_words(path)]


@dataclass(frozen=True)
class Detector:
    """One of the caller's own detectors: what ``pattern`` matches is removed as ``kind``
    and labelled ``label``. ``group`` is the part of the match to remove."""
    kind: str
    pattern: re.Pattern
    label: str = ""
    group: object = 0

    @classmethod
    def words(cls, kind, words, label=""):
        """A detector for a list of words and phrases, whole words, any case."""
        alternatives = sorted({w.strip() for w in words if w.strip()}, key=len, reverse=True)
        if not alternatives:
            raise ValueError("hush: the word list for %s is empty" % kind)
        body = "|".join(r"\s+".join(re.escape(part) for part in w.split()) for w in alternatives)
        return cls(kind, re.compile(r"(?<!\w)(?:" + body + r")(?!\w)", re.I), label)


class _Keep:
    """Names never redacted. Each kept person gives their full name in either order, a
    preferred name with the surname, each name alone, and a title with the surname or its
    initial ("Mrs Shah", "Miss S"). A lone kept surname straight after another capitalised
    name ("Margaret Shah") and a lone kept first name straight before another surname
    ("Priya Okafor") belong to someone else, so they are not kept. ``phrases`` are kept
    whole (product names, a team's name)."""

    _TITLE_INITIAL = re.compile(
        r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|MR|MRS|MS|MISS|MX|DR)\.?[ \t]+(?P<i>[A-Z])\b\.?"
        r"(?![ \t]*[A-Z][a-z])")

    def __init__(self, people=(), phrases=()):
        self.phrases = {}         # folded first word -> [folded words tuple]
        self.firsts, self.lasts, self.initials = set(), set(), set()
        for person in people:
            firsts = [person.first] + person.values("preferred")
            for first in [f for f in firsts if f]:
                self.firsts.update(fold(w) for w in _WORD.findall(first))
                self._add(first)
                if person.last:
                    self._add(first + " " + person.last)
                    self._add(person.last + " " + first)
            if person.last:
                self.lasts.update(fold(w) for w in _WORD.findall(person.last))
                self._add(person.last)
                self.initials.add(fold(person.last)[:1].upper())
        for phrase in phrases:
            self._add(phrase)
        for entries in self.phrases.values():
            entries.sort(key=len, reverse=True)

    def _add(self, phrase):
        words = tuple(fold(w) for w in _WORD.findall(phrase))
        if len(words) > 1:
            self.phrases.setdefault(words[0], []).append(words)

    def __bool__(self):
        return bool(self.phrases or self.firsts or self.lasts)

    def shield(self, text, mapping):
        return core._outside_tokens(text, lambda seg: self._change(seg, mapping), mapping)

    def _change(self, text, mapping):
        spans = []
        words = list(_WORD.finditer(text))
        cursor = 0
        for i, word in enumerate(words):
            if word.start() < cursor:
                continue
            raw = word.group(0)
            poss = _POSSESSIVE.search(raw)
            bare = raw[:poss.start()] if poss else raw
            folded = fold(bare)
            end = None
            for phrase in self.phrases.get(folded, ()):
                end = _match_phrase(text, words, i, phrase)
                if end is not None:
                    break
            if end is None and len(folded) >= 2 and (folded in self.firsts or folded in self.lasts):
                wordy = folded in english_words() or folded in name_words()
                if not (wordy and not bare[:1].isupper()) and self._alone(text, words, i, folded):
                    end = word.start() + len(bare)
            if end is not None:
                spans.append((word.start(), end))
                cursor = end
        for match in self._TITLE_INITIAL.finditer(text):
            if match.group("i") in self.initials and \
                    not any(s < match.end("i") and match.start("i") < e for s, e in spans):
                spans.append(match.span("i"))
        out = text
        for start, end in sorted(spans, reverse=True):
            out = out[:start] + mapping.token_for(text[start:end], "KEEP") + out[end:]
        return out

    def _alone(self, text, words, i, folded):
        """False when a lone kept name is part of another person's name."""
        if folded in self.lasts and i > 0:
            prev = words[i - 1].group(0)
            low = fold(prev).rstrip(".")
            gap = text[words[i - 1].end():words[i].start()]
            if re.fullmatch(r"[ \t]+", gap) and prev[:1].isupper() and \
                    low not in core._TITLES and low not in self.firsts and \
                    low not in core._GREETINGS:
                return False
        if folded in self.firsts and folded not in self.lasts and i + 1 < len(words):
            nxt = words[i + 1].group(0)
            gap = text[words[i].end():words[i + 1].start()]
            if re.fullmatch(r"[ \t]+", gap) and nxt[:1].isupper() and not nxt.isupper() and \
                    fold(nxt) not in self.lasts and fold(nxt) not in core.KEEP and \
                    fold(nxt) not in english_words():
                return False
        return True


def _with_known_forms(keep, known):
    """Kept people with the preferred names the known list gives the same person (same
    first name and surname), so keeping "Katarzyna Nowak" keeps "Kasia" too."""
    if not keep or not known:
        return keep
    preferred = {}
    for person in known:
        if person.key and person.preferred:
            preferred.setdefault(person.key, []).extend(person.values("preferred"))
    out = []
    for person in keep:
        extra = [v for v in preferred.get(person.key, ()) if v not in person.values("preferred")]
        if extra:
            person = replace(person, preferred=";".join(person.values("preferred") + extra))
        out.append(person)
    return out


class People:
    """The name detector for one kind of text. Build it once and reuse it.

    ``known`` is a list of :class:`Person` to remove, ``keep`` a list of :class:`Person`
    (or names as strings) never to remove. ``role`` is the role of a known person whose
    row names none. ``names`` turns the first-name list on (default) or off, and
    ``first_names`` adds names to it (another country's, a customer base's). ``any_case``
    lets first-name-list names match in lower case and capitals too. ``keep_words`` are
    words never taken as a name; a phrase of several words is kept whole. ``patterns``
    are the caller's own :class:`Detector` objects. ``login_labels`` adds words that
    label a login ("member"). ``columns`` maps extra column headers to fields, for tables
    pasted into the text. ``rules`` turns off the titled-name, login and handle rules
    (for measuring the patterns alone). Pass :meth:`detector` to the core's
    ``scrub(people=...)``.
    """

    def __init__(self, known=(), keep=(), *, names=True, any_case=False, role="person",
                 keep_words=(), patterns=(), login_labels=(), columns=None, first_names=(),
                 rules=True):
        self.people = list(known)
        self.keep_people = _with_known_forms(
            [p if isinstance(p, Person) else Person.from_name(p) for p in keep], self.people)
        self.names = names
        self.any_case = any_case
        self.role = role or "person"
        self.keep_words = tuple(keep_words)
        singles = [w for w in self.keep_words if len(w.split()) == 1]
        self.keep = frozenset(core.KEEP) | {fold(w) for w in singles} | {w.lower() for w in singles}
        self.keep_phrases = tuple(w for w in self.keep_words if len(w.split()) > 1)
        self.patterns = tuple(patterns)
        self.login_labels = tuple(login_labels)
        self.columns = dict(columns or {})
        self.extra_first_names = tuple(first_names)
        plain, wordy = split_names(self.extra_first_names)
        globals_first = _load("first_names.txt")
        self.first_names = globals_first | plain if plain else globals_first
        self.name_words = name_words() | wordy if wordy else name_words()
        self.rules = rules
        self._keep = _Keep(self.keep_people, self.keep_phrases)
        self._user_labelled = _user_labelled(self.login_labels)
        self._phrases = {}     # folded first word -> [(folded words tuple, kind)]
        self._single = {}      # folded word -> kind, for names that are not words
        self._careful = {}     # folded word -> kind, for name-words (capital only)
        self._ids = {}         # folded identifier -> kind
        self._who = {}         # folded value -> person key, when it names one person only
        self._build()

    def __repr__(self):
        return "People(known=%d, keep=%d, names=%s, any_case=%s)" % (
            len(self.people), len(self.keep_people), self.names, self.any_case)

    def _with(self, **changes):
        args = dict(known=self.people, keep=self.keep_people, names=self.names,
                    any_case=self.any_case, role=self.role, keep_words=self.keep_words,
                    patterns=self.patterns, login_labels=self.login_labels,
                    columns=self.columns, first_names=self.extra_first_names, rules=self.rules)
        args.update(changes)
        return People(**args)

    def with_people(self, known=(), keep=()):
        """A copy that also removes ``known`` and keeps ``keep``, for one text."""
        if not known and not keep:
            return self
        return self._with(known=self.people + list(known),
                          keep=self.keep_people + [p if isinstance(p, Person) else
                                                   Person.from_name(p) for p in keep])

    def kind_of(self, person):
        """The token kind for one known person, from their role or the default role."""
        return core.role_kind(person.role or self.role)

    def id_kind(self, value):
        """The kind of an identifier: the first of the caller's detectors that matches it
        whole, else ID."""
        for detector in self.patterns:
            if detector.pattern.fullmatch(value.strip()):
                return detector.kind
        return "ID"

    @property
    def labels(self):
        """{kind: label} from the caller's detectors."""
        return {d.kind: d.label for d in self.patterns if d.label}

    # --- building the index ------------------------------------------------------
    def _is_name_word(self, word):
        return fold(word) in self.name_words or fold(word) in self.keep

    def _claim(self, value, person):
        folded = fold(" ".join(value.split()))
        if not folded:
            return
        owner = self._who.get(folded)
        if owner is None and folded not in self._who:
            self._who[folded] = person.key
        elif owner != person.key:
            self._who[folded] = None   # two people share it: no single owner

    def _add_phrase(self, phrase, kind, person):
        words = tuple(fold(w) for w in _WORD.findall(phrase))
        if len(words) < 2:
            return
        self._phrases.setdefault(words[0], []).append((words, kind))
        self._claim(phrase, person)

    def _add_single(self, word, kind, person):
        for part in _WORD.findall(word):
            folded = fold(part)
            if len(folded) < 2:
                continue
            if self._is_name_word(part):
                self._careful.setdefault(folded, kind)
            else:
                self._single.setdefault(folded, kind)
            self._claim(part, person)
        if len(_WORD.findall(word)) > 1:          # "Mary-Jane", "Abdul Rahman" whole too
            self._add_phrase(word.replace("-", " "), kind, person)
            whole = fold(word)
            if "-" in word and " " not in word:
                self._single.setdefault(whole, kind)

    def _build(self):
        for person in self.people:
            kind = self.kind_of(person)
            firsts = [f for f in [person.first] + person.values("preferred") if f]
            for first in firsts:
                self._add_single(first, kind, person)
                if person.last:
                    for phrase in (first + " " + person.last, person.last + " " + first):
                        self._add_phrase(phrase, kind, person)
            if person.last:
                self._add_single(person.last, kind, person)
            for name, idkind in (("username", "USERNAME"), ("email", "EMAIL"), ("id", None)):
                for value in person.values(name):
                    self._ids[fold(value)] = idkind or self.id_kind(value)
                    self._claim(value, person)
        for first, entries in self._phrases.items():
            entries.sort(key=lambda e: len(e[0]), reverse=True)
        self._long_singles = {}
        for name, kind in list(self._single.items()) + list(self._careful.items()):
            if len(name) >= 6 and name.isalpha():
                self._long_singles[len(name)] = self._long_singles.get(len(name), ()) + ((name, kind),)

    @property
    def names_on_list(self):
        """Every folded single name on the known list."""
        return set(self._single) | set(self._careful)

    def who(self, value):
        """The person key a matched value names, or None when it names no one on the
        list or more than one person ("Aisha" with two Aishas on it)."""
        return self._who.get(fold(" ".join(value.split())))

    # --- matching ----------------------------------------------------------------
    def detector(self, text, mapping):
        """Keep the names to keep, then find known people, names and the caller's
        detectors in ``text`` and code them out with ``mapping``'s tokens. Runs only
        between tokens the mapping already issued. A table in the text that names its
        name columns adds its rows to the known list for this call."""
        if self._keep:
            text = self._keep.shield(text, mapping)
        extra = table_people(text, self.columns) if self.rules else []
        people = self if not extra else self._with(known=self.people + extra)
        return core._outside_tokens(text, lambda seg: people._change(seg, mapping), mapping)

    __call__ = detector

    def _change(self, segment, mapping):
        spans = self.find(segment)
        out = segment
        tokens = {}
        for start, end, kind in sorted(spans):
            tokens[(start, end)] = mapping.token_for(segment[start:end], kind)
        for start, end, kind in sorted(spans, reverse=True):
            out = out[:start] + tokens[(start, end)] + out[end:]
        return out

    def find(self, text):
        """``[(start, end, kind)]`` for every name and identifier in ``text``, longest
        first where two overlap. Public so a caller can test what would go."""
        found = []
        words = list(_WORD.finditer(text))
        if self.rules:
            found += self._find_titled(text)
        found += self._find_ids(text)
        if self.rules:
            found += self._find_usernames(text)
        for i, word in enumerate(words):
            found += self._at(text, words, i)
        found += self._find_misread(text, found)
        return _no_overlaps(found)

    def _find_titled(self, text):
        """A title and the name after it: "Mrs Pemberton", "Mr J. Okafor", "MS LINDQVIST".
        The title stays in the text and the name goes, as PERSON, or as the known
        person's kind when the whole name is on the list."""
        hits = []
        for match in _TITLED.finditer(text):
            start, end = match.span("name")
            name = match.group("name")
            if fold(name.split()[-1]) in self.keep or fold(name.split()[0]) in _NOT_AFTER_TITLE:
                continue
            kind = "PERSON"
            if self.who(name):
                kind = next((self.kind_of(p) for p in self.people if p.key == self.who(name)),
                            "PERSON")
            hits.append((start, end, kind))
        return hits

    def _is_namey(self, word):
        folded = fold(word)
        return folded in self._single or folded in self._careful or \
            (self.names and (folded in self.first_names or folded in self.name_words))

    def _find_usernames(self, text):
        """Logins, before any name rule can split one: an @handle ("@jordan.p"), a chat
        speaker shaped like a login at the start of a line ("[10:02] ms_bell:"), the value
        after a username label ("username: ella.w", "user=holly.a", ``"login": "kai.r"``),
        and anything shaped like a login that starts with a name ("freddie.h",
        "amberk3", "mo_khan")."""
        hits = []
        for match in _HANDLE_AT.finditer(text):
            if match.group("h").lower() not in SLACK_KEYWORDS:
                hits.append((match.start(), match.end(), "HANDLE"))
        for match in _SPEAKER.finditer(text):
            hits.append((match.start("s"), match.end("s"), "USERNAME"))
        words = english_words()
        for match in self._user_labelled.finditer(text):
            value = match.group("u").rstrip(".,;:)'\"-")
            sep = (match.group("sep") or "").lower()
            shaped = re.search(r"[\d._]", value)
            if sep in (":", "="):
                login_like = value == value.lower() or shaped
            elif sep in ("is", "was"):
                login_like = shaped or (value == value.lower() and value not in words)
            else:
                login_like = shaped
            if len(value) >= 2 and login_like and \
                    value.lower() not in ("none", "null", "n/a", "unknown", "is", "the"):
                hits.append((match.start("u"), match.start("u") + len(value), "USERNAME"))
        hits += self._login_shapes(text, words)
        for match in _USER_SHAPED.finditer(text):
            head, tail = match.group("head"), match.group("tail") or ""
            if len(tail) > 3:
                # "ella.wright" yes, "summer.term" and "max.value" no: a long tail needs a
                # head that is a name and not a word
                if fold(head) in self._single or (self.names and fold(head) in self.first_names):
                    hits.append((match.start(), match.end(), "USERNAME"))
                continue
            if self._is_namey(head) or (len(head) > 3 and self._is_namey(head[:-1])) or \
                    (len(head) > 4 and self._is_namey(head[:-2])):
                hits.append((match.start(), match.end(), "USERNAME"))
        return hits

    def _first_name(self, word):
        folded = fold(word)
        return folded in self._single or (self.names and folded in self.first_names)

    def _login_shapes(self, text, words):
        hits = []
        for match in _INITIAL_DOT.finditer(text):
            tail = match.group("tail")
            if tail not in words and tail not in _FILE_ENDINGS:
                hits.append((match.start(), match.end(), "USERNAME"))
        for match in _SPEAKER_WORD.finditer(text):
            if match.group("s") not in words and match.group("s") not in core.KEEP:
                hits.append((match.start("s"), match.end("s"), "USERNAME"))
        for shape in (_NAME_DIGITS, _NAME_DOT_NAME, _CAMEL_NAMES):
            for match in shape.finditer(text):
                if self._first_name(match.group("head")):
                    hits.append((match.start(), match.end(), "USERNAME"))
                elif shape is not _NAME_DIGITS and self.names:
                    # Two words joined by a dot or in capitals, neither of them English:
                    # "Nimali.Sivagnanam", "SomchaiHoang" (but not "TikTok")
                    parts = re.findall(r"[A-Z][a-z]+", match.group())
                    if len(parts) == 2 and all(len(p) > 3 and fold(p) not in words and
                                               fold(p) not in core.KEEP for p in parts):
                        hits.append((match.start(), match.end(), "USERNAME"))
        for match in _UNDERSCORED.finditer(text):
            parts = re.findall(r"[A-Z]?[a-z]+", match.group())
            if any(self._first_name(p) for p in parts if len(p) > 2):
                hits.append((match.start(), match.end(), "USERNAME"))
        return hits

    def _find_ids(self, text):
        hits = []
        for detector in self.patterns:
            for match in detector.pattern.finditer(text):
                start, end = match.span(detector.group)
                if end > start:
                    hits.append((start, end, detector.kind))
        if not self._ids:
            return hits
        for match in re.finditer(r"[\w.@+\-']+", text):
            raw = match.group(0).rstrip(".'-")
            kind = self._ids.get(fold(raw))
            if kind:
                hits.append((match.start(), match.start() + len(raw), kind))
        return hits

    def _at(self, text, words, i):
        word = words[i]
        raw = word.group(0)
        possessive = _POSSESSIVE.search(raw)
        bare = raw[:possessive.start()] if possessive else raw
        folded = fold(bare)
        start = word.start()
        # 1. known phrases: "Aisha Khan", "Khan, Aisha" (the comma is allowed), any case
        for phrase, kind in self._phrases.get(folded, ()):
            end = _match_phrase(text, words, i, phrase)
            if end is not None:
                return [(start, end, kind)]
        # 2. known single names that are not words: any case, except a two-letter name
        #    ("Jo", "Al"), which needs its capital
        kind = self._single.get(folded)
        if kind and (len(folded) > 2 or bare[:1].isupper()):
            return [(start, start + len(bare), kind)]
        # 3. known name-words: with a capital, in a name's place; in lower case only before
        #    a verb a person takes, or as a possessive ("ruby is", "faith hasn't", "grace's")
        kind = self._careful.get(folded)
        if kind and not bare.isupper():
            if bare[:1].isupper():
                if self._name_place(text, words, i, bare):
                    return [(start, start + len(bare), kind)]
            elif possessive or _next_on_line(text, words, i) in STRONG_NEXT:
                return [(start, start + len(bare), kind)]
        # 4. the first-name list, except straight after a word that puts a place next
        #    ("in Bradford", "from Jordan")
        if self.names and folded in self.first_names and folded not in self.keep and \
                folded not in core._FORM_WORDS and folded not in core._GREETINGS and \
                len(folded) >= 2 and not _after_place_word(text, words, i):
            titled = bare[:1].isupper() and not bare.isupper()
            if titled or (self.any_case and (bare.islower() or (bare.isupper() and len(bare) >= 3))):
                end = start + len(bare)
                if titled:
                    end = _surname_tail(text, words, i, start + len(bare), self.keep)
                elif bare.islower():
                    end = _lower_tail(text, words, i, end, self.keep)
                return [(start, end, "PERSON")]
        # 5. any capitalised word that is not an English word, before a verb only a person
        #    takes: "Brathwaite has been late", "Thảo has lost her planner"
        if self.rules and bare[:1].isupper() and not bare.isupper() and len(folded) >= 3 and \
                folded not in english_words() and folded not in self.keep and \
                folded not in core._FORM_WORDS and folded not in self.name_words and \
                folded not in self.first_names and not _after_place_word(text, words, i) and \
                _next_on_line(text, words, i) in STRONG_NEXT:
            return [(start, start + len(bare), "PERSON")]
        return []

    def _find_misread(self, text, taken):
        """Known names read off a screenshot with a letter wrong: "Zlelinski",
        "Carva1ho", "0luwaseun". A word of six letters or more that is one edit from a
        known name of six or more, or equal to one once 0, 1 and 5 read as o, l and s.
        Only words with a capital or a digit, and never a protected word."""
        if not self._long_singles:
            return []
        hits = []
        for match in _OCR_WORD.finditer(text):
            start, end = match.span()
            if any(s < end and start < e for s, e, _k in taken):
                continue
            raw = match.group(0)
            if not (raw[:1].isupper() or any(c.isdigit() for c in raw)):
                continue
            plain = fold(raw.translate(_OCR_DIGITS))
            if plain in self.keep or plain in self.name_words or plain in english_words() or \
                    not plain.isalpha():
                continue
            hit = None
            for folded in dict.fromkeys((plain, plain.replace("rn", "m"))):
                hit = self._single.get(folded) or self._careful.get(folded)
                if hit is None and len(folded) >= 6:
                    for name, kind in self._long_singles.get(len(folded), ()) + \
                            self._long_singles.get(len(folded) - 1, ()) + \
                            self._long_singles.get(len(folded) + 1, ()):
                        if _one_edit(folded, name):
                            hit = kind
                            break
                if hit:
                    break
            if hit:
                hits.append((start, end, hit))
        return hits

    def _name_place(self, text, words, i, bare):
        prev = words[i - 1].group(0).lower() if i > 0 else ""
        gap_before = text[words[i - 1].end():words[i].start()] if i > 0 else ""
        nxt = words[i + 1].group(0) if i + 1 < len(words) else ""
        gap_after = text[words[i].end():words[i + 1].start()] if i + 1 < len(words) else ""
        own = text[words[i].start() + len(bare):words[i].end()]
        if prev in BLOCK_BEFORE and gap_before.strip() == "":
            return False
        if nxt.lower() in BLOCK_NEXT and gap_after.strip() == "" and "\n" not in gap_after:
            return False
        if not _at_start(text, words[i].start()):
            return True
        if own:                                     # "Grace's", "Hope's"
            return True
        after = text[words[i].end():words[i].end() + 2]
        if not nxt or "\n" in gap_after or after[:1] in (",", ")", ":", ";", ".", "\t", "|"):
            return True                             # a list, a cell, a line on its own
        if nxt.lower() in SUBJECT_NEXT:
            return True
        # "Mason finds", "Faith enjoyed": a lower-case word shaped like a verb after it
        if nxt.islower() and len(nxt) >= 4 and re.search(r"(?:[^s]s|ed)\Z", nxt) and \
                nxt not in BLOCK_NEXT:
            return True
        # "Grace Okafor was...": a capitalised word after it that is not a protected word
        return nxt[:1].isupper() and fold(nxt) not in self.keep and \
            fold(nxt) not in core._FORM_WORDS and fold(nxt) not in BLOCK_NEXT


#: Lower-case words after a lower-case known name-word that make it a person: "ruby is",
#: "faith hasn't". Narrower than SUBJECT_NEXT: "will be" and "hope you" are not here.
STRONG_NEXT = {
    "is", "was", "has", "had", "isn't", "wasn't", "hasn't", "hadn't", "isnt", "wasnt",
    "hasnt", "didn't", "didnt", "doesn't", "doesnt", "can't", "cant", "won't", "wont",
    "needs", "got", "said", "says", "told", "asked", "wants", "went", "came", "left",
    "joined", "completed", "finished", "scored", "struggled", "missed", "forgot", "logged",
    "lost", "tried", "worked", "answered", "managed", "submitted",
}

#: A first-name-list word straight after one of these is read as a place.
PLACE_BEFORE = {"in", "near", "around", "across", "throughout", "from", "visit", "visiting",
                "via", "towards", "outside", "within"}

_OCR_WORD = re.compile(r"(?<![\w@.])[^\W_][\w'’\-]{4,}(?![\w@])")
_OCR_DIGITS = str.maketrans("015", "ols")


def _next_on_line(text, words, i):
    if i + 1 >= len(words):
        return ""
    gap = text[words[i].end():words[i + 1].start()]
    return words[i + 1].group(0).lower() if re.fullmatch(r"[ \t]+", gap) else ""


def _after_place_word(text, words, i):
    if i == 0:
        return False
    gap = text[words[i - 1].end():words[i].start()]
    poss = re.match(r"['’]s\b", text[words[i].end() - 2:words[i].end()]) is not None
    return words[i - 1].group(0).lower() in PLACE_BEFORE and re.fullmatch(r"[ \t]+", gap) \
        and not poss


#: Second words that make a name-word run a place, an event or a thing: "Hope Street",
#: "Summer Fair", "Poppy Appeal", "Rose Garden Road". BLOCK_NEXT holds the rest.
PLACE_HEADS = {
    "appeal", "award", "awards", "block", "bridge", "building", "campus", "centre", "center",
    "court", "crescent", "cup", "department", "estate", "foundation", "fund", "gate",
    "green", "grove", "hill", "library", "market", "method", "office", "place", "prize",
    "room", "row", "rule", "service", "services", "square", "station", "terrace",
    "theorem", "trust", "unit", "walk", "wing",
}
_CALENDAR = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}
#: A name that is also a word, alone, reads as the word before one of these: "Will you",
#: "Hope to", "Rose by 4%", "Can this".
WORD_USE_NEXT = {
    "you", "we", "they", "i", "he", "she", "it", "this", "that", "these", "those", "the",
    "a", "an", "your", "our", "my", "their", "his", "her", "its", "there", "be", "not",
    "to", "by", "up", "down", "out", "off", "so", "too", "all",
}
_GUESS_WORD = re.compile(r"[^\W\d_]+")
_NEXT_WORD = re.compile(r"[ \t]+([^\W\d_]+)")
_NAME_TOKEN_BEFORE = re.compile("(?:%s)[ \t]+\\Z" % core.TOKEN.pattern)


def _stems(word):
    if len(word) > 4 and word.endswith("ies"):
        yield word[:-3] + "y"
    if len(word) > 3 and word.endswith("es"):
        yield word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        yield word[:-1]
    if len(word) > 4 and word.endswith("ed"):
        yield word[:-2]
        yield word[:-1]
    if len(word) > 5 and word.endswith("ing"):
        yield word[:-3]
        yield word[:-3] + "e"


def _ordinary(folded, keep):
    """True for an English word, a protected word or a day or month, plurals included."""
    if folded in english_words() or folded in keep or folded in _CALENDAR:
        return True
    return any(stem in english_words() or stem in _CALENDAR for stem in _stems(folded))


def keep_guess(view, start, end):
    """Whether the core's capitalised-name guess may take ``view[start:end]``.

    Ordinary text is full of capitalised words that are not people: "Simultaneous
    Equations", "Access Arrangements", "Extra Time", "Deep Dive", "Click Submit". The
    guess may take a run only when one of these holds:

    1. a word in it is not an English word ("Oyelaran", "Brathwaite"), so likely a name;
    2. it opens with a name that is also a word and that 1,000 babies or more were given
       ("Grace", "Mason", "Hope"; not "Deep" or "Can"), and
       - goes on to capitalised words that are not a place or event ("Grace Baker"; not
         "Hope Street", "Summer Fair"), or
       - stands alone, not before a word that makes it the verb or the noun ("for Grant",
         "Mason is"; not "Will you", "Hope to");
    3. it sits straight after a name already taken ("<Grace> Baker").

    Protected words are those of the scrub in progress (``core.keep_words``).
    """
    words = _GUESS_WORD.findall(view[start:end])
    if not words:
        return True
    keep = core.keep_words()
    folded = [fold(w) for w in words]
    if any(not _ordinary(f, keep) for f in folded):
        return True
    if folded[0] in common_names():
        if len(folded) >= 2:
            if not any(f in BLOCK_NEXT or f in PLACE_HEADS for f in folded[1:]):
                return True
        else:
            following = _NEXT_WORD.match(view, end)
            if not following or following.group(1).lower() not in WORD_USE_NEXT:
                return True
    before = _NAME_TOKEN_BEFORE.search(view[max(0, start - 80):start])
    return bool(before and core.is_name_kind(before.group("kind")))


def _one_edit(a, b):
    """True when a and b differ by one substitution, insertion or deletion."""
    if a == b:
        return False
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    for k in range(len(b)):
        if b[:k] + b[k + 1:] == a:
            return True
    return False


def _match_phrase(text, words, i, phrase):
    """End of the phrase starting at word i, or None. Words may be split by spaces, one
    line break, a comma (for "Khan, Aisha") or a hyphen."""
    if i + len(phrase) > len(words):
        return None
    for k, want in enumerate(phrase):
        word = words[i + k].group(0)
        got = fold(word)
        last = k == len(phrase) - 1
        if got != want and not (last and _POSSESSIVE.search(word) and
                                fold(word[:_POSSESSIVE.search(word).start()]) == want):
            return None
        if k:
            gap = text[words[i + k - 1].end():words[i + k].start()]
            if not re.fullmatch(r"[ \t]*,?[ \t]*\n?[ \t]*|-", gap):
                return None
    end_word = words[i + len(phrase) - 1]
    poss = _POSSESSIVE.search(end_word.group(0))
    return end_word.end() - (len(poss.group(0)) if poss else 0)


def _surname_tail(text, words, i, end, keep):
    """Extend a first name over up to two capitalised surname words after it, with lower-case
    particles between ("Aisha Khan-Patel", "Daan van der Berg")."""
    k, taken = i + 1, 0
    while k < len(words) and taken < 2:
        gap = text[words[k - 1].end():words[k].start()]
        if not re.fullmatch(r"[ \t]+", gap):
            break
        word = words[k].group(0)
        low = word.lower()
        if low in PARTICLES:
            k += 1
            continue
        if not (word[:1].isupper() and not word.isupper()) or fold(word) in keep or \
                low in core._FORM_WORDS or low in BLOCK_NEXT:
            break
        poss = _POSSESSIVE.search(word)
        end = words[k].end() - (len(poss.group(0)) if poss else 0)
        taken += 1
        k += 1
    return end



def _lower_tail(text, words, i, end, keep):
    """In lower-case text (speech to text, chat), extend a first name over up to two
    lower-case words after it that are not English words: "daniel okafor", "li wei". A
    surname that is also a word ("smith", "baker") is not taken; the known list catches it."""
    k, taken = i + 1, 0
    while k < len(words) and taken < 2:
        gap = text[words[k - 1].end():words[k].start()]
        if not re.fullmatch(r"[ \t]+", gap):
            break
        word = words[k].group(0)
        low = fold(word)
        if low in PARTICLES:
            k += 1
            continue
        if not word.islower() or len(low) < 2 or low in english_words() or low in keep or \
                low in core._FORM_WORDS or low in BLOCK_NEXT or _POSSESSIVE.search(word):
            break
        end = words[k].end()
        taken += 1
        k += 1
    return end


def _no_overlaps(spans):
    spans = sorted(spans, key=lambda s: (s[0], -(s[1] - s[0])))
    kept, last_end = [], -1
    for start, end, kind in spans:
        if start >= last_end and end > start:
            kept.append((start, end, kind))
            last_end = end
    return kept
