"""Pupils' names: the class list first, a first-name list second, the core's guess last.

Why this order. A name the scrubber has been told about is matched exactly, in any
order and any case; a name it has not been told about has to be guessed from context, and
guesses miss. A school already holds the class list, so the class list does most of the
work, and the rest of this module is for the names it does not cover.

What it takes, and with what kind:

- **The roster** (``Person`` rows, usually read from a class-list CSV with
  :func:`read_roster`): every full name in four orders ("Aisha Khan", "Khan, Aisha",
  "Khan Aisha", the preferred name with the surname), each first, preferred and last name
  alone, and the person's username, email, UPN and ULN. Kind STUDENT, or STAFF for the
  staff list; identifiers keep their own kind (USERNAME, EMAIL, UPN, ULN).
- **The first-name list** (``lists/first_names.txt``, from the ONS baby names 1996 to
  2025): a name there is taken with a capital anywhere, including at the start of a
  sentence, where the core's guess leaves a single word alone. With ``any_case=True`` it
  is also taken in lower case or capitals ("jayden", "JAYDEN"). Kind PERSON.
- **Name-words** ("Grace", "Will", "Summer", "Mark": ``lists/name_words.txt``, names whose
  lower-case form is an English word) need care. On the roster they are taken only with a
  capital, never after "the", "a", "this" and the like, never before "Scheme", "Term",
  "Period" and the like, and at the start of a sentence only when the next word reads as
  something a person does ("Grace has", "Will is", "Hope's"). Off the roster they are left
  to the core's guess. A name-word in lower case is never taken: "grace" and "will" are
  words far more often than they are pupils.

Words the core protects (``KEEP``: subjects, days, product words) are never taken from
the first-name list, so "Pascal's triangle" and "Arbor" survive; a pupil called Pascal is
still taken when Pascal is on the roster.

Accents: every roster entry also goes in without its accents, so "Zoe" finds "Zoë".
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from hush import core

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
_CAP = r"(?:[A-Z][a-zà-ÿ]+(?:['’\-][A-Za-zà-ÿ]+)*|[A-Z]{2,}(?:['’\-][A-Z]+)*|[A-Z]\.?)"
_TITLED = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Sir|Dame|MR|MRS|MS|MISS|MX|DR)\.?[ \t]+"
    r"(?P<name>" + _CAP + r"(?:[ \t]+(?:(?:van|von|der|den|de|da|di|du|le|la|al|el|bin|ibn)[ \t]+)*"
    r"(?:[A-Z][a-zà-ÿ]+(?:['’\-][A-Za-zà-ÿ]+)*|[A-Z]{2,}(?:['’\-][A-Z]+)*)){0,2})"
    r"(?<![A-Z]\.)(?!['’][a-z]{2,})")
# A Unique Pupil Number (a check letter, 11 digits, then a digit or, for a temporary
# number, a letter) and a Unique Learner Number (10 digits), wherever they sit, URL paths
# and query strings included.
_UPN = re.compile(r"(?<![A-Za-z0-9])[A-Z]\d{11}[0-9A-Z](?![A-Za-z0-9])")
_ULN = re.compile(r"(?<![A-Za-z0-9.,])\d{10}(?![A-Za-z0-9]|[.,]\d)")
# An @handle, whole, so no name rule takes the name inside it; and a chat speaker at the
# start of a line, with an optional [time], shaped like a login: lower case with a dot or
# an underscore, or letters then digits ("ms_bell:", "sam.k:", "jdoe23:").
SLACK_KEYWORDS = {"here", "channel", "everyone"}
_HANDLE_AT = re.compile(r"(?<![\w@.])@(?P<h>[A-Za-z0-9_][A-Za-z0-9_.]{0,30}[A-Za-z0-9_])")
_SPEAKER = re.compile(r"(?m)^[ \t>]*(?:\[[0-9:. ]+(?:[AaPp][Mm])?\][ \t]*)?"
                      r"(?P<s>[a-z][a-z0-9]*[._][a-z0-9._]*[a-z0-9]|[a-z]{2,}\d{1,4})(?=:[ \t])")
# A login after its label, in prose, a log line or JSON.
_USER_LABELLED = re.compile(
    r"(?i)\b(?:user(?:[ _-]?name)?|login|log-in|pupil|student|learner|uid)[\"']?[ \t]*"
    r"(?:[:=]|\bis\b)[ \t]*[\"']?(?P<u>[A-Za-z][\w.'\-]{1,40})")
# A school login: a lower-case name and an initial or a surname after a dot or an
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


def _at_start(text, start):
    return start == 0 or bool(_STARTS.search(text[max(0, start - 6):start]))


def fold(text):
    """Lower case with accents taken off: "Zoë" and "zoe" fold the same."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


@lru_cache(maxsize=4)
def _load(name):
    path = DATA / name
    if not path.exists():
        return frozenset()
    return frozenset(fold(line.strip()) for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip())


def first_names():
    return _load("first_names.txt")


def name_words():
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


def table_people(text):
    """People in a table pasted into the text: a header row that names a name column
    (Forename, Surname, first_name, Name...) split by tabs, commas, semicolons or bars,
    and the rows under it until a blank line. An export carries its own class list."""
    people = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        found = False
        for delim in ("\t", ",", ";", "|"):
            if delim not in lines[i]:
                continue
            header = [c.strip().strip("*") for c in next(csv.reader([lines[i]], delimiter=delim))]
            roles = [column_role(c) if c else None for c in header]
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
                got = {}
                for role, value in zip(roles, row):
                    if role and value:
                        got[role] = value
                if "full" in got and not ("first" in got or "last" in got):
                    got["first"], got["last"] = _split_full(got.pop("full"))
                got.pop("full", None)
                if got.get("first") or got.get("last"):
                    people.append(Person(**got))
                j += 1
            i, found = j, True
            break
        if not found:
            i += 1
    return people


def is_name_word(word):
    """True when a name is also an English word, so it needs a capital and a name's place."""
    return fold(word) in name_words() or fold(word) in core.KEEP


@dataclass(frozen=True)
class Person:
    first: str = ""
    last: str = ""
    preferred: str = ""
    username: str = ""
    email: str = ""
    upn: str = ""
    uln: str = ""
    kind: str = "STUDENT"

    @property
    def key(self):
        """One string per person, for keyed pseudonyms: the folded legal name."""
        return fold(" ".join(p for p in (self.first, self.last) if p))


# Column names a class-list export uses, folded and with spaces and dashes as "_".
_COLUMNS = {
    "first": {"first", "first_name", "firstname", "forename", "forenames", "given_name",
              "given", "legal_forename", "legal_first_name", "first_names"},
    "last": {"last", "last_name", "lastname", "surname", "family_name", "legal_surname",
             "legal_last_name"},
    "preferred": {"preferred", "preferred_name", "preferred_forename", "known_as",
                  "nickname", "chosen_name", "preferred_first_name"},
    "full": {"name", "full_name", "fullname", "student", "student_name", "pupil",
             "pupil_name", "child", "child_name", "learner", "display_name"},
    "username": {"username", "user_name", "login", "user", "user_id", "student_username"},
    "email": {"email", "e_mail", "email_address", "school_email"},
    "upn": {"upn", "unique_pupil_number"},
    "uln": {"uln", "unique_learner_number"},
}


def column_role(header):
    key = re.sub(r"[\s\-]+", "_", fold(header.strip()))
    for role, names in _COLUMNS.items():
        if key in names:
            return role
    return None


def _split_full(full):
    full = " ".join(full.split())
    if "," in full:
        last, _, first = full.partition(",")
        return first.strip(), last.strip()
    parts = full.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def read_roster(path, kind="STUDENT"):
    """People from a CSV with a header row. Columns are found by name (see ``_COLUMNS``):
    Forename and Surname, or a single Name ("Aisha Khan" or "Khan, Aisha"), and any of
    preferred name, username, email, UPN and ULN. Other columns are ignored."""
    people = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        roles = {h: column_role(h) for h in (reader.fieldnames or ())}
        if not any(r in ("first", "last", "full") for r in roles.values()):
            raise ValueError("hush: %s has no name column (Forename, Surname or Name)" % path)
        for row in reader:
            got = {}
            for header, role in roles.items():
                if role and (row.get(header) or "").strip():
                    got[role] = row[header].strip()
            if "full" in got and not ("first" in got or "last" in got):
                got["first"], got["last"] = _split_full(got.pop("full"))
            got.pop("full", None)
            if got.get("first") or got.get("last"):
                people.append(Person(kind=kind, **got))
    return people


class Pupils:
    """The detector for one school's text. Build it once and reuse it.

    ``roster`` and ``staff`` are lists of :class:`Person`. ``names`` turns the first-name
    list on (default) or off. ``any_case`` lets first-name-list names match in lower case
    and capitals too. Pass ``detector`` to the core's ``scrub(students=...)``.
    """

    def __init__(self, roster=(), staff=(), *, names=True, any_case=False):
        self.people = [p for p in roster] + [p if p.kind == "STAFF" else
                                             Person(**{**p.__dict__, "kind": "STAFF"})
                                             for p in staff]
        self.names = names
        self.any_case = any_case
        self._phrases = {}     # folded first word -> [(folded words tuple, kind)]
        self._single = {}      # folded word -> kind, for names that are not words
        self._careful = {}     # folded word -> kind, for name-words (capital only)
        self._ids = {}         # folded identifier -> kind
        self._who = {}         # folded value -> person key, when it names one person only
        self._build()

    def __repr__(self):
        return "Pupils(people=%d, names=%s, any_case=%s)" % (len(self.people), self.names,
                                                             self.any_case)

    # --- building the index ------------------------------------------------------
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
            if is_name_word(part):
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
            kind = person.kind
            firsts = [f for f in (person.first, person.preferred) if f]
            for first in firsts:
                self._add_single(first, kind, person)
                if person.last:
                    for phrase in (first + " " + person.last, person.last + " " + first):
                        self._add_phrase(phrase, kind, person)
            if person.last:
                self._add_single(person.last, kind, person)
            for value, idkind in ((person.username, "USERNAME"), (person.email, "EMAIL"),
                                  (person.upn, "UPN"), (person.uln, "ULN")):
                if value:
                    self._ids[fold(value)] = idkind
                    self._claim(value, person)
        for first, entries in self._phrases.items():
            entries.sort(key=lambda e: len(e[0]), reverse=True)
        self._long_singles = {}
        for name, kind in list(self._single.items()) + list(self._careful.items()):
            if len(name) >= 6 and name.isalpha():
                self._long_singles[len(name)] = self._long_singles.get(len(name), ()) + ((name, kind),)

    @property
    def known(self):
        """Every folded single name on the roster and the staff list."""
        return set(self._single) | set(self._careful)

    def who(self, value):
        """The person key a matched value names, or None when it names no one on the
        roster or more than one person ("Aisha" with two Aishas in the year)."""
        return self._who.get(fold(" ".join(value.split())))

    # --- matching ----------------------------------------------------------------
    def detector(self, text, mapping):
        """Find pupils, staff and names in ``text`` and code them out with ``mapping``'s
        tokens. Runs only between tokens the mapping already issued. A table in the text
        that names its name columns adds its rows to the roster for this call."""
        extra = table_people(text)
        pupils = self if not extra else Pupils(self.people + extra, names=self.names,
                                                any_case=self.any_case)
        return core._outside_tokens(text, lambda seg: pupils._change(seg, mapping), mapping)

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
        """``[(start, end, kind)]`` for every name and roster identifier in ``text``,
        longest first where two overlap. Public so a caller can test what would go."""
        found = []
        words = list(_WORD.finditer(text))
        found += self._find_titled(text)
        found += self._find_ids(text)
        found += self._find_usernames(text)
        for i, word in enumerate(words):
            found += self._at(text, words, i)
        found += self._find_misread(text, found)
        return _no_overlaps(found)

    def _find_titled(self, text):
        """A title and the name after it: "Mrs Pemberton", "Mr J. Okafor", "MS LINDQVIST".
        The title stays in the text and the name goes, as PERSON (a teacher or a parent),
        or as the roster's kind when the whole name is on the roster."""
        hits = []
        for match in _TITLED.finditer(text):
            start, end = match.span("name")
            name = match.group("name")
            if fold(name.split()[-1]) in core.KEEP or fold(name.split()[0]) in _NOT_AFTER_TITLE:
                continue
            kind = "PERSON"
            if self.who(name):
                kind = next((p.kind for p in self.people if p.key == self.who(name)), "PERSON")
            hits.append((start, end, kind))
        return hits

    def _is_namey(self, word):
        folded = fold(word)
        return folded in self._single or folded in self._careful or \
            (self.names and (folded in first_names() or folded in name_words()))

    def _find_usernames(self, text):
        """Logins, before any name rule can split one: an @handle ("@jordan.p"), a chat
        speaker shaped like a login at the start of a line ("[10:02] ms_bell:"), the value
        after a username label ("username: ella.w", "user=holly.a", ``"login": "kai.r"``),
        and anything shaped like a school login that starts with a name ("freddie.h",
        "amberk3", "mo_khan")."""
        hits = []
        for match in _HANDLE_AT.finditer(text):
            if match.group("h").lower() not in SLACK_KEYWORDS:
                hits.append((match.start(), match.end(), "HANDLE"))
        for match in _SPEAKER.finditer(text):
            hits.append((match.start("s"), match.end("s"), "USERNAME"))
        for match in _USER_LABELLED.finditer(text):
            value = match.group("u").rstrip(".,;:)'\"-")
            login_like = value == value.lower() or re.search(r"[\d._]", value)
            if len(value) >= 2 and login_like and \
                    value.lower() not in ("none", "null", "n/a", "unknown", "is", "the"):
                hits.append((match.start("u"), match.start("u") + len(value), "USERNAME"))
        for match in _USER_SHAPED.finditer(text):
            head, tail = match.group("head"), match.group("tail") or ""
            if len(tail) > 3:
                # "ella.wright" yes, "summer.term" and "max.value" no: a long tail needs a
                # head that is a name and not a word
                if fold(head) in self._single or (self.names and fold(head) in first_names()):
                    hits.append((match.start(), match.end(), "USERNAME"))
                continue
            if self._is_namey(head) or (len(head) > 3 and self._is_namey(head[:-1])) or \
                    (len(head) > 4 and self._is_namey(head[:-2])):
                hits.append((match.start(), match.end(), "USERNAME"))
        return hits

    def _find_ids(self, text):
        hits = [(m.start(), m.end(), "UPN") for m in _UPN.finditer(text)]
        hits += [(m.start(), m.end(), "ULN") for m in _ULN.finditer(text)]
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
        # 1. roster phrases: "Aisha Khan", "Khan, Aisha" (the comma is allowed), any case
        for phrase, kind in self._phrases.get(folded, ()):
            end = _match_phrase(text, words, i, phrase)
            if end is not None:
                return [(start, end, kind)]
        # 2. roster single names that are not words: any case, except a two-letter name
        #    ("Jo", "Al"), which needs its capital
        kind = self._single.get(folded)
        if kind and (len(folded) > 2 or bare[:1].isupper()):
            return [(start, start + len(bare), kind)]
        # 3. roster name-words: with a capital, in a name's place; in lower case only before
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
        if self.names and folded in first_names() and folded not in core.KEEP and \
                folded not in core._FORM_WORDS and folded not in core._GREETINGS and \
                len(folded) >= 2 and not _after_place_word(text, words, i):
            titled = bare[:1].isupper() and not bare.isupper()
            if titled or (self.any_case and (bare.islower() or (bare.isupper() and len(bare) >= 3))):
                end = start + len(bare)
                if titled:
                    end = _surname_tail(text, words, i, start + len(bare))
                return [(start, end, "PERSON")]
        # 5. any capitalised word that is not an English word, before a verb only a person
        #    takes: "Brathwaite has been late", "Thảo has lost her planner"
        if bare[:1].isupper() and not bare.isupper() and len(folded) >= 3 and \
                folded not in english_words() and folded not in core.KEEP and \
                folded not in core._FORM_WORDS and folded not in name_words() and \
                folded not in first_names() and not _after_place_word(text, words, i) and \
                _next_on_line(text, words, i) in STRONG_NEXT:
            return [(start, start + len(bare), "PERSON")]
        return []

    def _find_misread(self, text, taken):
        """Roster names read off a screenshot with a letter wrong: "Zlelinski",
        "Carva1ho", "0luwaseun". A word of six letters or more that is one edit from a
        roster name of six or more, or equal to one once 0, 1 and 5 read as o, l and s.
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
            if plain in core.KEEP or plain in name_words() or plain in english_words() or \
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
        return nxt[:1].isupper() and fold(nxt) not in core.KEEP and \
            fold(nxt) not in core._FORM_WORDS and fold(nxt) not in BLOCK_NEXT


#: Lower-case words after a lower-case roster name-word that make it a person: "ruby is",
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


def _ordinary(folded):
    """True for an English word, a protected word or a day or month, plurals included."""
    if folded in english_words() or folded in core.KEEP or folded in _CALENDAR:
        return True
    return any(stem in english_words() or stem in _CALENDAR for stem in _stems(folded))


def keep_guess(view, start, end):
    """Whether the core's capitalised-name guess may take ``view[start:end]``.

    School text is full of capitalised words that are not people: "Simultaneous
    Equations", "Access Arrangements", "Extra Time", "Deep Dive", "Click Submit". The guess
    may take a run only when one of these holds:

    1. a word in it is not an English word ("Oyelaran", "Brathwaite"), so likely a name;
    2. it opens with a name that is also a word and that 1,000 babies or more were given
       ("Grace", "Mason", "Hope"; not "Deep" or "Can"), and
       - goes on to capitalised words that are not a place or event ("Grace Baker"; not
         "Hope Street", "Summer Fair"), or
       - stands alone, not before a word that makes it the verb or the noun ("for Grant",
         "Mason is"; not "Will you", "Hope to");
    3. it sits straight after a name already taken ("<Grace> Baker").
    """
    words = _GUESS_WORD.findall(view[start:end])
    if not words:
        return True
    folded = [fold(w) for w in words]
    if any(not _ordinary(f) for f in folded):
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
    return bool(before and before.group("kind") in core.NAME_KINDS)


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
    """End of the roster phrase starting at word i, or None. Words may be split by spaces,
    one line break, a comma (for "Khan, Aisha") or a hyphen."""
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


def _surname_tail(text, words, i, end):
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
        if not (word[:1].isupper() and not word.isupper()) or fold(word) in core.KEEP or \
                low in core._FORM_WORDS or low in BLOCK_NEXT:
            break
        poss = _POSSESSIVE.search(word)
        end = words[k].end() - (len(poss.group(0)) if poss else 0)
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
