"""What each removed value becomes. Detection always makes core tokens first; a style
then rewrites every token this Mapping issued, so all four styles find the same things.

- ``token``: leave the tokens. Reversible with :func:`hush.core.restore` in the same
  process, which is what an AI round trip needs.
- ``label``: "[person 1]", "[customer 2]", "[email 1]". Numbered by label in order of
  first appearance, so "[person 1]" is the same person all the way down. One way.
- ``pseudonym``: "Person-3F9A1C", "EMAIL-81D2E0". A keyed hash (HMAC-SHA256) of the value,
  or of the person when the known list says which person a value names, so the same
  person gets the same code in every file and every run that uses the same key. Without
  the key the code cannot be turned back into the name; with it, anyone can test a
  guess, so the key is a secret.
- ``fake``: a made-up name in the real one's place ("Aisha Khan" -> "Megan Walsh"), and
  example.com emails and Ofcom drama-range phone numbers, for demos and screenshots. The
  same real value gets the same fake within one run, and across runs with the same key.
  Other kinds become labels.

In every style a value of a kind in ``leave`` (names to keep, kinds the config flags)
goes back into the text as it was written.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from hush import core
from hush.core import fold
from hush.people import DATA, first_names, name_words

STYLES = ("token", "label", "pseudonym", "fake")

LABELS = {
    "PERSON": "person", "CLINICIAN": "person", "PLACE": "place", "EMAIL": "email",
    "PHONE": "phone", "DATE": "date", "YEAR": "year", "DOB": "date of birth", "CODE": "code",
    "NUMBER": "number", "POSTCODE": "postcode", "ADDRESS": "address", "HOMEADDR": "address",
    "HANDLE": "username", "USERNAME": "username", "SECRET": "secret", "URL": "link",
    "NHSNUM": "NHS number", "NINO": "NI number", "CARD": "card", "SORTCODE": "sort code",
    "ACCOUNTNO": "account number", "IBAN": "account", "BIC": "bank code", "IP": "IP address",
    "PASSPORT": "passport", "LICENCE": "licence", "MRN": "record number",
    "SAID": "ID number", "ID": "ID", "TOKEN": "token",
}

# Common surnames for the fake style. Invented people need ordinary surnames from the
# whole of a British population, not one tradition.
FAKE_SURNAMES = (
    "Smith Jones Taylor Brown Williams Wilson Johnson Davies Robinson Wright Thompson Evans "
    "Walker White Roberts Green Hall Wood Jackson Clarke Patel Khan Ahmed Ali Hussain Begum "
    "Shah Singh Kaur Sharma Okafor Adeyemi Mensah Owusu Mohamed Hassan Abdi Kowalski Nowak "
    "Popescu Murphy Kelly O'Brien Walsh Byrne Chen Wang Li Nguyen Tran Yilmaz Santos Silva "
    "Costa Campbell Stewart Morris Hughes Edwards Turner Hill Moore Cooper Ward King Baker "
    "Harris Lewis Martin Scott Young Allen Mitchell Phillips Parker Bennett Carter Collins "
    "Bell Shaw Murray Price Lloyd Ellis Cox Richardson Fox Mills Grant Reid Rahman Uddin "
    "Iqbal Akhtar Mahmood Bello Okoro Nwosu Boateng Asante Lewandowski Wiśniewski Ionescu"
).split()

# Plain, common first names for the fake style, drawn once from the first-name list so
# fakes look like real names. Falls back to a short list if the data file is missing.
_FALLBACK_FIRST = ("Amelia Olivia Isla Ava Mia Ivy Lily Freya Zara Aisha Maryam Fatima Grace "
                   "Oliver George Noah Arthur Leo Muhammad Harry Oscar Jack Theo Yusuf Adam "
                   "Ibrahim Samuel Daniel Kai").split()


def label_for(kind, labels=None):
    """What a kind is called in a label: the caller's own label, the built-in one, the
    role of a known person ("PERSON_CUSTOMER" is "customer"), or the kind in lower case."""
    if labels and kind in labels:
        return labels[kind]
    if kind in LABELS:
        return LABELS[kind]
    if kind.startswith("PERSON_"):
        kind = kind[len("PERSON_"):]
    return kind.lower().replace("_", " ")


def _fake_firsts():
    """{"g": girls' names, "b": boys' names, "x": the rest, "all": every one}."""
    pools = {"g": [], "b": [], "x": []}
    path = DATA / "common_first_names.txt"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, _, sex = line.strip().partition("\t")
            if name:
                pools.get(sex or "x", pools["x"]).append(name)
    pools = {k: tuple(v) for k, v in pools.items()}
    pools["all"] = pools["g"] + pools["b"] + pools["x"]
    if len(pools["all"]) < 100:
        pools = {"g": (), "b": (), "x": (), "all": _FALLBACK_FIRST}
    return pools


_SEX = None


def sex_of(name):
    """"g", "b" or None for a real first name, from the ONS counts (lists/name_sex.txt)."""
    global _SEX
    if _SEX is None:
        _SEX = {}
        path = DATA / "name_sex.txt"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                entry, _, sex = line.partition("\t")
                if entry:
                    _SEX[fold(entry)] = sex.strip()
    return _SEX.get(fold(name))


def _same_text(text, issued, who):
    """``who`` widened for one text: a lone first name or surname that is the first or
    last word of exactly one full name in the same text is that person ("Gareth Lyle",
    then "Gareth"), so both get one label. Across texts it stays as ``who`` says."""
    fulls = {}
    for match in core.TOKEN.finditer(text):
        real = issued.get(match.group(0))
        if real and core.is_name_kind(match.group("kind")) and len(real.split()) > 1:
            words = [fold(w) for w in real.split()]
            for word in {words[0], words[-1]}:
                fulls.setdefault(word, set()).add(fold(" ".join(real.split())))
    if not fulls:
        return who

    def lookup(value):
        found = who(value)
        if found is not None or len(value.split()) != 1:
            return found
        owners = fulls.get(fold(value), ())
        if len(owners) != 1:
            return None
        (full,) = owners
        return who(full) or full
    return lookup


class Renderer:
    """Turns one Mapping's tokens into a style. Keep one Renderer for a run that spans
    several texts or files, so labels, pseudonyms and fakes stay the same across them."""

    def __init__(self, style="label", *, key=None, who=None, exclude=(), labels=None,
                 leave=("KEEP",)):
        """``who`` maps a real name to a person key (``People.who``); ``exclude`` is
        folded names a fake must never be, usually every name on the known list.
        ``labels`` maps kinds to the caller's own labels. ``leave`` is kinds put back as
        written."""
        if style not in STYLES:
            raise ValueError("hush: style must be one of %s" % ", ".join(STYLES))
        self.style = style
        self.keyed = key is not None
        self.key = key if key is not None else secrets.token_bytes(32)
        self.who = who or (lambda value: None)
        self.exclude = set(exclude)
        self.labels = dict(labels or {})
        self.leave = frozenset(leave)
        self._labels = {}      # (label, folded value) -> number
        self._counts = {}
        self._fakes = {}
        self._used = set()
        self._firsts = None

    def render(self, text, mapping, *, who=None, roles=None):
        """The text in this style. See :meth:`render_spans`."""
        return self.render_spans(text, mapping, who=who, roles=roles)[0]

    def render_spans(self, text, mapping, *, who=None, roles=None):
        """``(out, spans)``: the text in this style, and ``(start, end, kind, token)`` for
        each token in it, with its place in ``out``. ``who`` overrides the person lookup
        for this text; ``roles`` maps a token to a role that relabels it (``PERSON_`` and
        the role)."""
        issued = mapping.by_token
        roles = roles or {}
        lookup = _same_text(text, issued, who or self.who)
        pieces, spans, cursor, length = [], [], 0, 0
        for match in core.TOKEN.finditer(text):
            token = match.group(0)
            real = issued.get(token)
            if real is None:
                continue
            kind = match.group("kind")
            if token in roles:
                kind = core.role_kind(roles[token])
            if kind in self.leave or match.group("kind") in self.leave:
                value = real
            elif self.style == "token":
                value = token
            else:
                value = self.value(kind, real, who=lookup)
            before = text[cursor:match.start()]
            pieces.append(before)
            length += len(before)
            spans.append((length, length + len(value), kind, token))
            pieces.append(value)
            length += len(value)
            cursor = match.end()
        pieces.append(text[cursor:])
        return "".join(pieces), spans

    def value(self, kind, real, *, who=None):
        """What one real value of one kind becomes in this style."""
        if self.style == "label":
            return self._label(kind, real, who)
        if self.style == "pseudonym":
            return self._pseudonym(kind, real, who)
        if self.style == "fake":
            return self._fake(kind, real, who)
        raise ValueError("hush: the token style has no value form")

    def label(self, kind):
        return label_for(kind, self.labels)

    def _label(self, kind, real, who=None):
        label = self.label(kind)
        name = core.is_name_kind(kind)
        ident = (who or self.who)(real) if name else None
        key = (label, ident or (fold(real) if name else real))
        if key not in self._labels:
            self._counts[label] = self._counts.get(label, 0) + 1
            self._labels[key] = self._counts[label]
        return "[%s %d]" % (label, self._labels[key])

    def _digest(self, material):
        return hmac.new(self.key, material.encode("utf-8"), hashlib.sha256).hexdigest().upper()

    def _pseudonym(self, kind, real, who=None):
        if core.is_name_kind(kind):
            ident = (who or self.who)(real)
            material = "person\0" + (ident or fold(" ".join(real.split())))
            prefix = "Person" if kind == "CLINICIAN" else self.label(kind).title().replace(" ", "")
            return "%s-%s" % (prefix, self._digest(material)[:6])
        if kind in ("DATE", "DOB"):
            return self._label(kind, real)
        material = "%s\0%s" % (kind, fold(real.strip()))
        return "%s-%s" % (self.label(kind).upper().replace(" ", ""), self._digest(material)[:6])

    def _pick(self, pool, material):
        """A stable choice from pool for material, moving on past values already used."""
        start = int(self._digest(material)[:8], 16)
        for step in range(len(pool)):
            pick = pool[(start + step) % len(pool)]
            if pick not in self._used and fold(pick) not in self.exclude:
                self._used.add(pick)
                return pick
        return pool[start % len(pool)]

    def fake_surname(self, real):
        """A made-up surname for a real one, the same one wherever this surname appears."""
        key = ("PART", True, fold(real))
        if key not in self._fakes:
            self._fakes[key] = self._pick(FAKE_SURNAMES, "fake\0%d\0%s" % (True, fold(real)))
        return self._fakes[key]

    def _fake(self, kind, real, who=None):
        name = core.is_name_kind(kind) and kind != "PLACE"
        cache_key = (kind if not name else "NAME", fold(real))
        if cache_key in self._fakes:
            return self._fakes[cache_key]
        if name:
            if self._firsts is None:
                self._firsts = _fake_firsts()
            parts = re.findall(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", real)
            out = []
            for i, part in enumerate(parts):
                if len(parts) == 1:   # a first name alone, or a surname alone ("Mrs Pemberton")
                    surname = not (fold(part) in first_names() or fold(part) in name_words())
                else:
                    surname = i > 0
                if surname:
                    pool = FAKE_SURNAMES
                else:
                    sex = sex_of(part)
                    pool = self._firsts.get(sex) or self._firsts["all"]
                known = self._fakes.get(("PART", surname, fold(part)))
                if known is None:
                    known = self._pick(pool, "fake\0%d\0%s" % (surname, fold(part)))
                    self._fakes[("PART", surname, fold(part))] = known
                out.append(known)
            fake = " ".join(out) if out else self._label(kind, real, who)
            if real[:1].islower():
                fake = fake.lower()
        elif kind == "EMAIL":
            fake = "user%s@example.com" % self._digest("email\0" + fold(real))[:5].lower()
        elif kind == "PHONE":
            fake = "07700 900%03d" % (int(self._digest("phone\0" + real)[:6], 16) % 1000)
        elif kind in ("USERNAME", "HANDLE"):
            fake = "user%s" % self._digest("user\0" + fold(real))[:5].lower()
        else:
            fake = self._label(kind, real, who)
        self._fakes[cache_key] = fake
        return fake
