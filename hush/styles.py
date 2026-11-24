"""What each removed value becomes. Detection always makes core tokens first; a style
then rewrites every token this Mapping issued, so all four styles find the same things.

- ``token``: leave the tokens. Reversible with :func:`hush.core.restore` in the same
  process, which is what an AI round trip needs.
- ``label``: "[student 1]", "[staff 2]", "[email 1]". Numbered by kind in order of first
  appearance in this text, so "[student 1]" is the same pupil all the way down. One way.
- ``pseudonym``: "Pupil-3F9A1C", "UPN-81D2E0". A keyed hash (HMAC-SHA256) of the value, or
  of the person when the roster says which person a value names, so the same pupil gets
  the same code in every file and every run that uses the same key. Without the key the
  code cannot be turned back into the name; with it, anyone can test a guess, so the key
  is a secret.
- ``fake``: a made-up name in the real one's place ("Aisha Khan" -> "Megan Walsh"), and
  example.com emails and Ofcom drama-range phone numbers, for demos and screenshots. The
  same real value gets the same fake within one run, and across runs with the same key.
  Other kinds become labels.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from hush import core
from hush.students import DATA, first_names, fold, name_words

STYLES = ("token", "label", "pseudonym", "fake")

LABELS = {
    "STUDENT": "student", "STAFF": "staff", "PERSON": "person", "CLINICIAN": "person",
    "PLACE": "place", "EMAIL": "email", "PHONE": "phone", "DATE": "date",
    "DOB": "date of birth", "CODE": "code", "NUMBER": "number", "POSTCODE": "postcode",
    "ADDRESS": "address", "HOMEADDR": "address", "HANDLE": "username",
    "USERNAME": "username", "UPN": "UPN", "ULN": "ULN", "SECRET": "secret", "URL": "link",
    "NHSNUM": "NHS number", "NINO": "NI number", "CARD": "card", "SORTCODE": "sort code",
    "ACCOUNT": "account", "IP": "IP address", "IBAN": "account",
}
PREFIX = {"STUDENT": "Pupil", "STAFF": "Staff", "PERSON": "Person", "CLINICIAN": "Person"}
NAME_KINDS = {"STUDENT", "STAFF", "PERSON", "CLINICIAN"}

# Common surnames for the fake style. Invented people need ordinary surnames from the
# whole of a British school roll, not one tradition.
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
# fakes look like the real roll. Falls back to a short list if the data file is missing.
_FALLBACK_FIRST = ("Amelia Olivia Isla Ava Mia Ivy Lily Freya Zara Aisha Maryam Fatima Grace "
                   "Oliver George Noah Arthur Leo Muhammad Harry Oscar Jack Theo Yusuf Adam "
                   "Ibrahim Samuel Daniel Kai").split()


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
                name, _, sex = line.partition("\t")
                if name:
                    _SEX[fold(name)] = sex.strip()
    return _SEX.get(fold(name))


class Renderer:
    """Turns one Mapping's tokens into a style. Keep one Renderer for a run that spans
    several texts or files, so labels, pseudonyms and fakes stay the same across them."""

    def __init__(self, style="label", *, key=None, who=None, exclude=()):
        """``who`` maps a real name to a person key (``Pupils.who``); ``exclude`` is
        folded names a fake must never be, usually every name on the roster."""
        if style not in STYLES:
            raise ValueError("hush: style must be one of %s" % ", ".join(STYLES))
        self.style = style
        self.keyed = key is not None
        self.key = key if key is not None else secrets.token_bytes(32)
        self.who = who or (lambda value: None)
        self.exclude = set(exclude)
        self._labels = {}      # (label, folded value) -> number
        self._counts = {}
        self._fakes = {}
        self._used = set()
        self._firsts = None

    def render(self, text, mapping):
        if self.style == "token":
            return text
        issued = mapping.by_token

        def repl(match):
            token = match.group(0)
            real = issued.get(token)
            if real is None:
                return token
            return self.value(match.group("kind"), real)
        return core.TOKEN.sub(repl, text)

    def value(self, kind, real):
        """What one real value of one kind becomes in this style."""
        if self.style == "label":
            return self._label(kind, real)
        if self.style == "pseudonym":
            return self._pseudonym(kind, real)
        if self.style == "fake":
            return self._fake(kind, real)
        raise ValueError("hush: the token style has no value form")

    def _label(self, kind, real):
        label = LABELS.get(kind, kind.lower().replace("_", " "))
        ident = self.who(real) if kind in NAME_KINDS else None
        key = (label, ident or (fold(real) if kind in NAME_KINDS else real))
        if key not in self._labels:
            self._counts[label] = self._counts.get(label, 0) + 1
            self._labels[key] = self._counts[label]
        return "[%s %d]" % (label, self._labels[key])

    def _digest(self, material):
        return hmac.new(self.key, material.encode("utf-8"), hashlib.sha256).hexdigest().upper()

    def _pseudonym(self, kind, real):
        if kind in NAME_KINDS:
            ident = self.who(real)
            material = "person\0" + (ident or fold(" ".join(real.split())))
            return "%s-%s" % (PREFIX.get(kind, "Person"), self._digest(material)[:6])
        if kind in ("DATE", "DOB"):
            return self._label(kind, real)
        material = "%s\0%s" % (kind, fold(real.strip()))
        return "%s-%s" % (LABELS.get(kind, kind).upper().replace(" ", ""), self._digest(material)[:6])

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

    def _fake(self, kind, real):
        cache_key = (kind if kind not in NAME_KINDS else "NAME", fold(real))
        if cache_key in self._fakes:
            return self._fakes[cache_key]
        if kind in NAME_KINDS:
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
            fake = " ".join(out) if out else self._label(kind, real)
            if real[:1].islower():
                fake = fake.lower()
        elif kind == "EMAIL":
            fake = "user%s@example.com" % self._digest("email\0" + fold(real))[:5].lower()
        elif kind == "PHONE":
            fake = "07700 900%03d" % (int(self._digest("phone\0" + real)[:6], 16) % 1000)
        elif kind in ("USERNAME", "HANDLE"):
            fake = "user%s" % self._digest("user\0" + fold(real))[:5].lower()
        else:
            fake = self._label(kind, real)
        self._fakes[cache_key] = fake
        return fake
