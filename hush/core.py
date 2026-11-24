"""hush core: take the identity out of a piece of writing, and put it back in the reply.

Two ideas carry it.

1. **A naive scrubber destroys the question.** Strip every capitalised word and "Can
   Teams export the March Report on Monday?" becomes unanswerable. ``KEEP`` protects a
   vocabulary, so the product word, the month and the day stay in the text. A caller adds
   its own words for one scrub (``keep=``): product names, a sector's vocabulary.

2. **A one-way scrub makes an AI's answer useless.** If the reply comes back about a
   token, the reader has to translate it in their head. So every substitution is recorded
   in a :class:`Mapping` and :func:`restore` puts the real words back into the reply.

The detectors come in packs (``PACKS``) that a caller turns on or off: ``general`` (emails,
links, IP addresses, cards, IBANs, international phones, dates, long numbers, codes,
labelled secrets, handles), ``uk`` (NHS and National Insurance numbers, bank details, UK
phones, postcodes, house-number addresses), ``north-america`` (phone numbers) and
``south-africa`` (ID numbers, Afrikaans and Dutch street names).

What it removes, in this order:

- tokens it did not issue (a forged token is sealed, never trusted);
- columns headed as secrets in a table;
- email addresses and links, whole, so a name inside an address never splits it;
- the caller's own detector, if one is passed (``people=``: see ``hush.people``);
- the roster: names the caller already knows, as whole words, ignoring case;
- JSON fields named as names, emails, phones, addresses, dates of birth;
- identifiers by label, shape and check digit, from the packs turned on;
- every full date (a DATE token), every code that mixes letters with two or more digits
  (CODE), and every run of six digits or more (NUMBER), label or not;
- last, a guess at capitalised names from their neighbours (``heuristic_names``).

Tokens carry a namespace and a keyed check: ``<P…_PERSON_0001_…>``. :func:`restore`
replaces only exact tokens this Mapping issued; anything else shaped like a token is
counted as a restore miss and left alone. It never guesses.

The mapping lives in memory only. Nothing in this module writes to disk or uses the
network. Standard library only. For one Mapping the output is deterministic.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

TOKEN_VERSION = "hush-token-v1"

# --- what must survive the scrub -------------------------------------------
# A capitalised word here is vocabulary, not identity. A false entry costs a leaked
# common noun; a missing entry costs a mangled question. KEEP never removes anything:
# it only stops the name rules from taking a word. Known names and every pattern still
# apply. This is the general list; a config adds its own (``keep=`` on :func:`scrub`).
KEEP = {
    # the calendar
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec", "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
    "autumn", "spring", "summer",
    # people by role, and the groups they work in
    "teacher", "teachers", "student", "students", "parent", "parents", "carer", "carers",
    "department", "group", "trust",
    # software and service words that start with a capital
    "teams", "google", "microsoft", "chromebook", "ipad", "sso", "oauth", "csv",
    "optional", "target", "targets", "task", "tasks", "check", "checks", "login",
    "dashboard", "report", "reports", "insights", "settings", "support", "help",
    # roles, headings and column names that start with a capital
    "data", "manager", "officer", "coordinator", "co-ordinator", "lead", "leader",
    "director", "administrator", "admin", "assistant", "technician", "librarian",
    "receptionist", "trustee", "chair", "bursar", "business", "board", "level", "type",
    "meeting", "agenda", "minutes", "scheme", "reg", "registration", "preferred", "legal",
    "trip", "visit", "policy", "consent", "letter", "newsletter",
    "score", "scores", "result", "results", "grade", "grades", "marks", "progress",
    "status", "complete", "completed", "incomplete", "overdue", "submitted", "pending",
    # a few health words that turn up in letters
    "nhs", "gp", "a&e", "adhd", "asd", "autism", "dyslexia", "dyscalculia", "dyspraxia",
    "asthma", "epipen", "covid",
}


def fold(text):
    """Lower case with accents taken off: "Zoë" and "zoe" fold the same."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


# The words in force for the scrub in progress: KEEP and the caller's own. Set by
# :func:`scrub` for the length of one call, so two configs in one process never mix.
_ACTIVE_KEEP = contextvars.ContextVar("hush_keep", default=None)


def keep_words(extra=()):
    """The folded words that are never a name: KEEP, the words of the scrub in progress,
    and ``extra``."""
    active = _ACTIVE_KEEP.get()
    base = active if active is not None else frozenset(KEEP)
    if not extra:
        return base
    return base | {fold(w) for w in extra} | {w.lower() for w in extra}

# A word built like a specialty, a test or a condition is medicine whatever its root:
# "Rheumatology", "Rheumatologist", "arthritis", "colonoscopy", "angiogram".
_CLINICAL_SUFFIX = re.compile(
    r"(?i)[a-z]{3,}(?:ology|ologist|ologists|ological|iatry|iatrist|iatrics|itis|ectomy|"
    r"otomy|ostomy|oscopy|ography|ogram|aemia|emia|algia|osis|pathy|plasty)\Z")

# Month words that are also first names: before a capitalised surname they are a name
# ("April Moss", "May Quill"), and anywhere else a month.
_NAME_LIKE_KEEP = {"april", "may", "june", "august"}

# Words that label a form field, and greetings. They never join a name, so "Account No"
# and "Hospital number" are not taken for people (which would also hide the label from
# the residual check), and "Dear Ada" leaves "Dear" alone. Straight after a title they
# are surnames like any other ("Dr Best").
_FORM_WORDS = {
    "account", "acc", "acct", "no", "nos", "number", "num", "ref", "reference",
    "passport", "hospital", "patient", "patients", "name", "names", "surname", "forename",
    "date", "birth", "dob", "sort", "code", "card", "policy", "member", "membership",
    "customer", "client", "address", "postcode", "post", "phone", "telephone", "tel",
    "mobile", "mob", "email", "fax", "id", "insurance", "national", "bank", "details",
    "iban", "licence", "license", "driving", "expiry", "expires", "issue", "issued",
    "valid", "signature", "signed", "holder", "title", "gender", "sex", "age", "contact",
    "kin", "next", "practice", "booking", "order", "invoice", "claim", "case", "file",
    "record", "records", "subject", "re", "from", "to", "cc", "bcc", "attn", "fao",
    "ward", "clinic", "unit", "department", "dept", "pin", "password", "username",
    "first", "last", "full", "given", "family", "middle", "maiden", "payee", "payer",
    "beneficiary", "cardholder", "applicant", "claimant",
} | {
    # rooms and the parts of a building: "Room 214", "Seminar Room 3", "Bed 14"
    "room", "bed", "bay", "level", "floor", "suite", "theatre", "block", "wing", "gate",
    "platform", "desk", "office", "lab", "building", "zone", "booth", "cubicle", "lounge",
    "studio", "hall", "lift", "warehouse",
} | {
    # table and order labels
    "registration", "substitution", "substitutions", "total", "subtotal", "item", "items",
    "qty", "quantity", "price", "amount", "balance", "description", "status", "notes",
    "note", "comments", "comment", "summary", "vat", "delivery", "collection", "discount",
} | {
    # the labels of payslips, tax notices, statements and prescriptions
    "personal", "allowance", "allowances", "medical", "underpaid", "overpaid", "income",
    "gross", "net", "annual", "monthly", "weekly", "daily", "basic", "overtime", "holiday",
    "pension", "rate", "week", "weeks", "session", "sessions", "medicine", "medicines",
    "dose", "dosage", "frequency", "due", "paid", "owed", "refund", "credit", "debit",
    "opening", "closing", "fee", "charge", "deposit", "interest", "deduction",
    "deductions", "earnings", "salary", "wage", "wages", "bonus", "benefit", "benefits",
    "contribution", "contributions", "employer", "employee", "period", "venue",
}
# Determiners: "Your Direct Debit", "The Occupier", "My Account" are things, not people.
_DETERMINERS = {"your", "my", "our", "the", "this", "that", "these", "those", "their", "his",
                "her", "its", "every", "each", "any", "some"}
_GREETINGS = _DETERMINERS | {"dear", "hi", "hello", "hey", "thanks", "thank", "regards", "best", "kind",
              "warm", "yours", "sincerely", "faithfully", "cheers", "love", "morning",
              "afternoon", "evening", "good"}

# --- the token --------------------------------------------------------------
# A token holds a namespace, the kind, a four-digit index and a keyed check. A model that
# copies a token exactly gets the real words back; one that alters it gets a counted miss,
# never a near guess.
TOKEN = re.compile(
    r"<(?P<namespace>P[0-9A-F]{16})_(?P<kind>[A-Z][A-Z0-9_]{1,31})_"
    r"(?P<index>\d{4})_(?P<check>[0-9A-F]{16})>"
)
_TOKEN_BODY_LIKE = re.compile(
    r"(?i)(?<![A-Z0-9])P[0-9A-F]{16}(?=_|\Z)")
# Eight or more hex digits after the P: a namespace is sixteen, and "[PDF]" is a word.
_TOKEN_OPEN_PREFIX_LIKE = re.compile(
    r"(?i)(?:<|\[|\{|:)\s*P[0-9A-F]{8,}[A-Z0-9_]*(?:>|\]|\}|\Z)")
_KIND = re.compile(r"[A-Z][A-Z0-9_]{1,31}\Z")

#: Kinds whose values are names: matched and restored without regard to case. A known
#: person with a role has the kind ``PERSON_`` and the role ("PERSON_CUSTOMER"), which is
#: a name kind too (:func:`is_name_kind`).
NAME_KINDS = frozenset({"PERSON", "CLINICIAN", "PLACE"})


def is_name_kind(kind):
    """True for a kind whose values are people's names or places."""
    return kind in NAME_KINDS or kind.startswith("PERSON_")


def role_kind(role):
    """The token kind for a person with ``role``: PERSON for none or "person", else
    PERSON_ and the role in capitals ("customer" gives PERSON_CUSTOMER)."""
    word = re.sub(r"[^A-Z0-9]+", "_", (role or "").strip().upper()).strip("_")
    if not word or word == "PERSON":
        return "PERSON"
    return ("PERSON_" + word)[:32].rstrip("_")


def kind_of(token):
    """The kind a token names, or None when the text is not a token."""
    match = TOKEN.fullmatch(token)
    return match.group("kind") if match else None


class Mapping:
    """The record of what was replaced by what, held in memory and nowhere else.

    ``by_real`` maps each real string to its token, so the same consultant is the same
    token for every scrub that shares this Mapping. A name is looked up without regard
    to case, so "Dr Quill" and "dr quill" do not become two people, and the reply carries
    the spelling seen first. Every other value is looked up exactly, so two secrets that
    differ only in case come back as themselves. ``day_offset`` is kept at zero: dates are
    coded out, never shifted. There is no save and no load: a Mapping ends with the
    process that made it.
    """

    def __init__(self, *, day_offset=0):
        self.namespace = "P" + secrets.token_hex(8).upper()
        self._key = secrets.token_bytes(32)
        self.by_real = {}
        self.counters = {}
        self.day_offset = day_offset
        self._keys = {}
        self._real = {}

    def __repr__(self):
        return "Mapping(namespace=%s, values=%d)" % (self.namespace, len(self.by_real))

    @property
    def by_token(self):
        return dict(self._real)

    def issued(self):
        """Every token this Mapping has issued."""
        return set(self._real)

    def check_for(self, kind, index):
        material = ("%s\0%s\0%s\0%04d" % (TOKEN_VERSION, self.namespace, kind, index))
        return hmac.new(self._key, material.encode("ascii"),
                        hashlib.sha256).hexdigest()[:16].upper()

    def token_for(self, real, kind):
        """The stable token for one real string, allocated on first sight."""
        if not _KIND.match(kind):
            raise ValueError("hush: %r is not a token kind" % kind)
        key = ("name", real.lower()) if is_name_kind(kind) else ("value", real)
        known = self._keys.get(key)
        if known is not None:
            return known
        index = self.counters.get(kind, 0) + 1
        if index > 9999:
            raise ValueError("hush: more than 9999 values of kind %s in one mapping" % kind)
        self.counters[kind] = index
        token = "<%s_%s_%04d_%s>" % (self.namespace, kind, index, self.check_for(kind, index))
        self.by_real.setdefault(real, token)
        self._keys[key] = token
        self._real[token] = real
        return token

    def copy(self):
        """A second Mapping with the same namespace, key and values, changed apart."""
        twin = Mapping.__new__(Mapping)
        twin.namespace = self.namespace
        twin._key = self._key
        twin.by_real = dict(self.by_real)
        twin.counters = dict(self.counters)
        twin.day_offset = self.day_offset
        twin._keys = dict(self._keys)
        twin._real = dict(self._real)
        return twin


# --- letters ----------------------------------------------------------------
# The old capitalised-word pattern was ASCII, so "Zoë", "Élodie" and "Téo" slipped
# past it. Python's re has no \p{Lu}, so the classes are built once from str.isupper
# and str.islower over Latin, Greek and Cyrillic.
def _letter_class(test):
    spans, run = [], None
    for code in range(0x41, 0x2000):
        char = chr(code)
        if char.isalpha() and test(char):
            if run and run[1] == code - 1:
                run[1] = code
            else:
                if run:
                    spans.append(run)
                run = [code, code]
    if run:
        spans.append(run)
    return "".join(re.escape(chr(a)) if a == b else "%s-%s" % (re.escape(chr(a)), re.escape(chr(b)))
                   for a, b in spans)


_U = _letter_class(str.isupper)
_L = _letter_class(str.islower)


# --- the view every pattern reads -------------------------------------------------
# HTML-derived text is full of no-break and thin spaces, letters and statements use en
# dashes in numbers, and some forms use fullwidth digits. Each is one character for one
# here, so a match found in the view has the same span in the text, and the token keeps
# the original characters.
_VIEW = {
    **{code: " " for code in (0x00A0, 0x1680, *range(0x2000, 0x200B), 0x202F, 0x205F,
                              0x3000)},
    **{code: "-" for code in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212,
                              0xFE58, 0xFE63, 0xFF0D)},
    **{0xFF10 + n: str(n) for n in range(10)},
    0xFF0B: "+", 0xFF20: "@",
    0x0D: " ",
}


# Form boxes and separators between single characters ("|1|4|0|3|", "[J][K][4]",
# "☐2☐0☐4") read as spaces, one for one, so the characters read as a spaced number.
_BOX = "|[]¦☐☑☒□▢◻⬜▯"
_BOX_CLASS = "[" + re.escape(_BOX) + "]"
_BOXED = re.compile("(?:" + _BOX_CLASS + "+[A-Za-z0-9]){3,}" + _BOX_CLASS + "*")


def _view(text):
    view = text.translate(_VIEW)
    if any(char in view for char in _BOX):
        view = _BOXED.sub(lambda m: re.sub(_BOX_CLASS, " ", m.group(0)), view)
    return view


_OCR_DIGIT = re.compile(r"(?<=\d)[OoIl]+|[OoIl]+(?=\d)")
_OCR_MAP = str.maketrans("OoIl", "0011")


def _ocr_digits(view):
    """A scan's letters O and l beside a digit read as the digits they stand for, one for
    one ("O77OO" is "07700"). Used by the date rules and the number pass only, never by
    the name guess."""
    return _OCR_DIGIT.sub(lambda m: m.group(0).translate(_OCR_MAP), view)


# --- the rules ----------------------------------------------------------------
@dataclass(frozen=True)
class _Rule:
    """One pattern. ``group`` is the part replaced (0 is the whole match), ``check`` a
    function that is handed the replaced text and returns the (start, end) to take
    within it, or None to leave the match alone. ``groups``, when given, names several
    (group, kind) parts of one match, each replaced by its own token. ``context``, when
    given, is handed the view and the span and says whether to take it. ``pack`` is the
    pack the rule belongs to (``PACKS``)."""
    kind: str
    pattern: re.Pattern
    group: object = 0
    check: object = None
    groups: tuple = ()
    context: object = None
    ocr: bool = False
    pack: str = "general"


def _digits(text):
    return re.sub(r"\D", "", text)


def _luhn_ok(digits):
    """Standard mod-10 check. A false positive here scrubs a reference number the
    reader needed; a false negative leaks a card. Luhn is what the payment world uses
    to tell the difference, so it is what is used here."""
    total, alt = 0, False
    for char in reversed(digits):
        if not char.isdigit():
            return False
        number = int(char)
        if alt:
            number *= 2
            if number > 9:
                number -= 9
        total += number
        alt = not alt
    return total % 10 == 0


def _nhs_ok(digits):
    """The NHS number's mod-11 check: weights 10 down to 2 on the first nine digits, the
    tenth is 11 minus the remainder, 11 reads as 0, and 10 means no valid number."""
    if len(digits) != 10:
        return False
    total = sum(int(d) * w for d, w in zip(digits[:9], range(10, 1, -1)))
    check = 11 - total % 11
    if check == 11:
        check = 0
    return check != 10 and check == int(digits[9])


def _iban_ok(text):
    """The IBAN mod-97 check, so a lower-case IBAN is taken only when it is a real one."""
    compact = re.sub(r"\s", "", text).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", compact):
        return False
    moved = compact[4:] + compact[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def _card_check(text):
    digits = _digits(text)
    if 13 <= len(digits) <= 19 and len(set(digits)) > 1 and _luhn_ok(digits):
        return 0, len(text)
    return None


def _nhs_check(text):
    return (0, len(text)) if _nhs_ok(_digits(text)) else None


def _iban_check(text):
    return (0, len(text)) if _iban_ok(text) else None


def _digit_span(low, high):
    """Accept a run of digit groups when its digit count is within [low, high]. A run
    that is too long is refused whole rather than cut short, so its tail is never left
    behind: the number pass then takes all of it."""
    def check(text):
        groups = list(re.finditer(r"\(?\d+\)?", text))
        if groups and low <= len(_digits(text)) <= high:
            return 0, groups[-1].end()
        return None
    return check


def _broken_digit_span(low, high):
    """As `_digit_span`, for a run that must also carry a space, dot, dash or bracket."""
    within = _digit_span(low, high)

    def check(text):
        taken = within(text)
        if taken is None or not re.search(r"[ .()-]", text[taken[0]:taken[1]]):
            return None
        return taken
    return check


# An extension after a phone number goes with it: "ext 11037", "ext. 5", "x12",
# "extension 204", "(ext. 220)". Only straight after a number shape, so "2 x 3" and
# "extension work" stay.
_EXT_BODY = (r"[ \t]*[,;]?[ \t]*\(?(?i:ext(?:ension)?\.?|x)[ \t]*(?i:no\.?)?[ \t]*[.:#]?[ \t]*"
             r"\d{1,6}\)?")
_EXT = r"(?:" + _EXT_BODY + r"(?![\w]))?"
_EXT_TAIL = re.compile(_EXT_BODY + r"\Z")


def _with_extension(check=None):
    """Run ``check`` on a phone match without its extension, then give back the whole
    match, extension and all, when there is one."""
    def wrapped(text):
        tail = _EXT_TAIL.search(text)
        head = text[:tail.start()] if tail else text
        taken = check(head) if check is not None else (0, len(head))
        if taken is None:
            return None
        return (taken[0], len(text)) if tail else taken
    return wrapped


def _labelled_phone_check(text):
    """A labelled phone is one number: a + number of 8 to 15 digits, a UK or North
    American one of 10 or 11."""
    return (_digit_span(8, 15) if text.startswith("+") else _digit_span(10, 11))(text)


def _bare_link_check(text):
    trimmed = text.rstrip(".,;:!?'\")]}")
    return (0, len(trimmed)) if len(trimmed) > trimmed.index("/") + 1 else None


def _url_check(text):
    trimmed = text.rstrip(".,;:!?'\")]}")
    head = re.match(r"(?i)https?://|www\.", trimmed)
    return (0, len(trimmed)) if head and len(trimmed) > head.end() else None


def _ipv6_check(text):
    return (0, len(text)) if re.search(r"\d", text) and text.count(":") >= 2 else None


def _postcode_label_check(text):
    """A labelled postcode in a broken shape ("G one, one X W") is taken at its word,
    as long as it carries a letter and a digit or a spelled digit."""
    has_digit = re.search(r"\d|(?i:zero|oh|one|two|three|four|five|six|seven|eight|nine)", text)
    has_letter = re.search(r"\b[A-Z]{1,2}\b|[A-Z]\d", text)
    return (0, len(text)) if has_digit and has_letter else None


def _postcode_check(text):
    """A postcode in capitals is taken as it stands. In lower or mixed case it must also
    keep Royal Mail's inward rule (the last two letters are never C, I, K, M, O or V) and
    not read as an ordinal, so "m2 3rd" stays prose."""
    if text.upper() == text:
        return 0, len(text)
    inward = re.sub(r"\s", "", text)[-3:]
    if re.fullmatch(r"\d(?:st|nd|rd|th)", inward, re.I) or re.search(r"[cikmov]", inward[1:], re.I):
        return None
    return 0, len(text)


def _rx(text, flags=0):
    return re.compile(text, flags)


_SPELLED = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)"
# From a label to its value: spaces, "is", a colon, hash, equals, dash or table bar,
# and at most one line break.
def _handle_context(view, start, end):
    """A value after a login label with no colon or equals sign needs to look like a login,
    a digit, a dot, an underscore or an @ in it, or not be an English word: "the login was
    successful" keeps its word."""
    if re.search(r"[:=#|][\s*\"']*\Z", view[max(0, start - 8):start]):
        return True
    value = view[start:end]
    if re.search(r"[\d._@]", value):
        return True
    from hush.people import english_words
    return value == value.lower() and value not in english_words() and value not in KEEP


_GAP = r"[ \t]*\**[ \t]*(?:is[ \t]+)?[:#=|-]*[ \t]*\**[ \t]*(?:\n[ \t]*)?"
# A short phrase between a cue and its number on the same line, or the cue ending its
# line and the number starting the next. A cue never reads into the next line's prose.
_NEAR = r"(?:[^\n\d]{0,24}?|[ \t]*[:#|.-]?[ \t]*\n[ \t]*)"
# Between two groups of digits: up to three spaces, or a dot, dash or slash.
_GS = r"(?:[ \t]{1,3}|[ \t]*[./-][ \t]*)"
_NO_MORE_DIGITS = r"(?!" + _GS + r"?\d)"
_SORT_VALUE = r"\d{2}" + _GS + r"?\d{2}" + _GS + r"?\d{2}"
_TEN_DIGITS = r"\d(?:" + _GS + r"?\d){9}"
_DATE_VALUE = (r"\d{1,2}(?:st|nd|rd|th)?[ \t]+(?:of[ \t]+)?[A-Za-z]{3,9}[ \t,]+\d{4}"
               r"|\d{1,2}[ \t]*[/.-][ \t]*\d{1,2}[ \t]*[/.-][ \t]*\d{2,4}|\d{4}-\d{2}-\d{2}")

# Taken whole before the roster runs, because an address or a link often carries a
# name inside it, and splitting it would leave its other half behind.
_FIRST = (
    # An apostrophe may sit inside the name half ("sean.o'neill@"), not before it, so an
    # address in single quotes is still found.
    _Rule("EMAIL", _rx(r"(?<![\w.+-])[\w.+-][\w.+'’-]*[ \t]?@[ \t]?[\w-]+(?:\.[\w-]+)+")),
    # "ada.quill (at) example (dot) test", written out to slip past a filter.
    _Rule("EMAIL", _rx(
        r"(?i)(?<![\w.+-])[\w.+'’-]+[ \t]*[(\[{][ \t]*at[ \t]*[)\]}][ \t]*[\w-]+"
        r"(?:(?:[ \t]*[(\[{][ \t]*dot[ \t]*[)\]}][ \t]*|\.)[\w-]+)+")),
    # An address read out: "ada dot quill at example dot net".
    _Rule("EMAIL", _rx(
        r"(?i)\b[a-z0-9]+(?:[ \t]+dot[ \t]+[a-z0-9]+)*[ \t]+at[ \t]+[a-z0-9-]+"
        r"(?:[ \t]+dot[ \t]+[a-z0-9-]+)*[ \t]+dot[ \t]+(?:com|net|org|uk|co|io|gov|nhs|ac|edu|"
        r"info|biz|me|test|example|za|nl|de|fr|ie|eu)\b")),
    # Case-insensitive, and a scheme is found even glued to the word before it, as text
    # taken from HTML often has it ("click herehttps://...").
    _Rule("URL", _rx(r"(?i)(?:https?://|www\.)[^\s<>\"'`]+"), check=_url_check),
    # A domain with a path and no scheme ("profile1.example.test/member/x") is a link too.
    _Rule("URL", _rx(
        r"(?i)(?<![\w@./-])(?:[a-z0-9-]+\.)+[a-z]{2,24}/[^\s<>\"'`]*"), check=_bare_link_check),
)


# --- addresses ------------------------------------------------------------------
# A street address is a number, one to four name words and a street word, then what may
# follow it: a direction, a flat or suite, a town, a state, county or province, a postal
# code and a country. Found before the people step, so a street or a town named like a
# person ("22 Jordan Avenue", "Silverholt") goes with its address. A number and a word
# that is not a street word is not an address: "3 Big Boxes", "5 minutes down the road".
_STREET_WORDS = (r"Street|St|Road|Rd|Avenue|Ave|Av|Lane|Ln|Drive|Dr|Boulevard|Blvd|Way|"
                 r"Court|Ct|Place|Pl|Terrace|Terr|Close|Crescent|Cres|Parkway|Pkwy|Highway|"
                 r"Hwy|Circle|Cir|Trail|Trl|Square|Sq|Mews|Grove|Gardens|Alley|Plaza")
_ABBREVIATED = {"st", "rd", "ave", "av", "ln", "dr", "blvd", "ct", "pl", "terr", "cres",
                "pkwy", "hwy", "cir", "trl", "sq"}
_DIRECTION = r"(?:N|S|E|W|NE|NW|SE|SW|North|South|East|West)\.?"
# Words that never start or sit inside a street's name: "Step 2 Fill In The Way".
_NOT_IN_A_STREET = (r"(?:In|To|Of|And|For|On|At|By|With|From|Into|Your|My|Our|Their|His|Her|"
                    r"This|That|These|Those|Is|Are|Was|Be|A|An|Or|If|We|You|They|It|I)")
_STREET_NAME_WORD = (r"(?!" + _NOT_IN_A_STREET + r"\b)(?:[" + _U + r"](?:[\w'’-]*\w)?\.?|"
                     r"\d{1,3}(?:st|nd|rd|th))")
_HOUSE_NUMBER = (r"\d{1,6}(?:/\d{1,4})?(?:[ ]?[A-Ha-h](?![\w'’]))?(?:-\d{1,4}[A-Ha-h]?)?"
                 r"(?![\w'’])")
_UNIT_WORD = r"(?:Apt|Apartment|Suite|Ste|Unit|Flat|Floor|Fl|Bldg|Building|Room|Rm)\.?"
_UNIT = r"(?:" + _UNIT_WORD + r"[ \t]*#?[ \t]*[A-Za-z0-9][A-Za-z0-9-]{0,5}|#[ \t]?\d{1,5}[A-Za-z]?)"
_US_STATES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|"
              "Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|"
              "Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|"
              "Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|"
              "Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|"
              "Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|"
              "District of Columbia|Puerto Rico|Ontario|Quebec|British Columbia|Alberta|"
              "Manitoba|Saskatchewan|Nova Scotia|New Brunswick|Newfoundland and Labrador|"
              "Prince Edward Island")
_REGION_CODES = ("AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
                 "MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|"
                 "DC|PR|ON|QC|BC|AB|MB|SK|NS|NB|NL|PE|YT|NT|NU")
_REGION = (r"(?:(?:" + _REGION_CODES + r")(?![\w])|(?:" + _US_STATES + r")\b|[" + _U
           + r"][a-z]+(?:[ \t][" + _U + r"][a-z]+)?[ \t]County\b)")
_POSTAL = (r"(?:\d{5}(?:-\d{4})?(?!\d)|[A-Z]\d[A-Z][ \t]?\d[A-Z]\d\b|"
           r"[A-Z]{1,2}\d[A-Z\d]?[ \t]?\d[A-Z]{2}\b)")
_COUNTRY = (r"(?:USA|U\.S\.A\.|US|United[ \t]States(?:[ \t]of[ \t]America)?|Canada|UK|"
            r"United[ \t]Kingdom|England|Scotland|Wales|Northern[ \t]Ireland|Ireland|"
            r"Australia|New[ \t]Zealand)\b")
# A town after a comma: one to three capitalised words, not a word that starts a sentence.
_TOWN_WORD = (r"(?!" + _NOT_IN_A_STREET + r"\b|(?:The|Then|But|So|Please|Thanks|Thank|He|She|"
              r"Call|Ring|Phone|Email|Tel|Postcode|Zip|County)\b)[" + _U + r"][^\W\d_]+"
              r"(?:['’-][^\W\d_]+)*(?![\w])(?:\.(?=[ \t]+[" + _U + r"]))?")
_TOWN = _TOWN_WORD + r"(?:[ \t]+" + _TOWN_WORD + r"){0,2}"
# After the street: a direction, a flat or a road number ("Dr 36", "Hwy 84"), up to two
# towns or districts, a state, a postal code, a country, and a postal code after it.
_ADDRESS_TAIL = (r"(?:[ \t]+" + _DIRECTION + r"(?![\w]))?"
                 r"(?:,?[ \t]*" + _UNIT + r"|[ \t]+\d{1,5}[A-Za-z]?(?![\w]|[.,:/-]\d))?"
                 r"(?:,[ \t]*(?!" + _REGION + r"|" + _COUNTRY + r")" + _TOWN + r"){0,2}"
                 r"(?:,?[ \t]+" + _REGION + r")?"
                 r"(?:,?[ \t]+" + _POSTAL + r")?"
                 r"(?:,[ \t]*" + _COUNTRY + r"(?:,?[ \t]+" + _POSTAL + r")?)?")
_STREET_ADDRESS = re.compile(
    r"(?<![\w.,/-])(?:" + _UNIT + r",?[ \t]+)?" + _HOUSE_NUMBER + r",?[ \t]+"
    r"(?:The[ \t]+)?(?:" + _DIRECTION + r"[ \t]+)?(?:" + _STREET_NAME_WORD + r"[ \t]+){1,4}?"
    r"(?P<type>" + _STREET_WORDS + r")\b(?P<dot>\.(?=[ \t]*[,;]|[ \t]+(?:[a-z]|" + _UNIT_WORD
    + r"|#|\d)))?" + _ADDRESS_TAIL)
# The street word first, or a name and then the street word, and the number after:
# "Via Roma, 42", "Calle El Conde 105", "Ulitsa Tverskaya, 19", "Herzl Street 14".
_FRONT_STREET_WORDS = (r"Via|Viale|Corso|Piazza|Calle|Avenida|Av\.|Avda\.?|Rua|Rue|Strada|"
                       r"Ulitsa|Ul\.|Carrera|Carretera|Praça|Plaza|Paseo|Camino|Boulevard|Bd\.?|"
                       r"Allee|Chaussée|Straße|Strasse|Ulica")
_PARTICLE_WORD = r"(?:de|del|della|di|da|das|dos|do|des|du|la|le|el|al|van|von|der|den|y|e)"
_CONTINENTAL_ADDRESS = re.compile(
    r"(?<![\w.-])(?:(?:" + _FRONT_STREET_WORDS + r")[ \t]+(?:(?:" + _STREET_NAME_WORD + r"|"
    + _PARTICLE_WORD + r"|\d{1,3})[ \t]+){0,4}(?:" + _STREET_NAME_WORD + r"|\d{1,3})|(?:"
    + _STREET_NAME_WORD + r"[ \t]+){1,3}(?:" + _STREET_WORDS + r")\.?)"
    r",?[ \t]+(?:No\.?[ \t]*|#[ \t]?)?\d{1,5}[A-Ha-h]?(?:[ \t]*[/#-][ \t]*\d{1,5}(?:-\d{1,4})?)?"
    r"(?![\w]|[.,:/-]\d)" + _ADDRESS_TAIL)
_PO_BOX = re.compile(
    r"(?i:\b(?:P\.?[ \t]?O\.?[ \t]?Box|Post[ \t]Office[ \t]Box))[ \t]*#?[ \t]*\d{1,7}\b"
    + r"(?:,[ \t]*(?!" + _REGION + r")" + _TOWN + r")?(?:,?[ \t]+" + _REGION + r")?"
    r"(?:,?[ \t]+" + _POSTAL + r")?(?:,[ \t]*" + _COUNTRY + r")?")
# A town, a state or province and a ZIP code with no street: "Murfreesboro, TN 37130".
_TOWN_REGION_ZIP = re.compile(
    r"(?<![\w.-])(?:" + _TOWN + r",[ \t]*)?(?:" + _REGION_CODES + r"|" + _US_STATES + r"),?"
    r"[ \t]+\d{5}(?:-\d{4})?(?![\d-])")
# A Canadian postal code: letter, digit, letter, then digit, letter, digit.
_CANADIAN_POSTCODE = re.compile(
    r"(?<![A-Za-z0-9])[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ \t-]?\d[ABCEGHJ-NPRSTV-Z]\d"
    r"(?![A-Za-z0-9])")


def _address_spans(view, packs):
    spans = []
    if "general" in packs:
        for match in _STREET_ADDRESS.finditer(view):
            end = match.end()
            spans.append((match.start(), end, "ADDRESS"))
        spans += [(m.start(), m.end(), "ADDRESS") for m in _PO_BOX.finditer(view)]
        spans += [(m.start(), m.end(), "ADDRESS") for m in _CONTINENTAL_ADDRESS.finditer(view)]
    if "north-america" in packs:
        spans += [(m.start(), m.end(), "ADDRESS") for m in _TOWN_REGION_ZIP.finditer(view)]
        spans += [(m.start(), m.end(), "POSTCODE") for m in _CANADIAN_POSTCODE.finditer(view)]
    return spans


def _scrub_addresses(text, mapping, packs):
    """Street addresses, post office boxes and, in the north-america pack, a town with
    its state and ZIP code and a Canadian postal code. Longest first where two overlap."""
    def change(segment):
        view = _view(segment)
        spans = sorted(_address_spans(view, packs), key=lambda s: (s[0], -(s[1] - s[0])))
        pieces, cursor = [], 0
        for start, end, kind in spans:
            start, end = _strip_span(view, start, end)
            if start < cursor or start >= end:
                continue
            pieces.append(segment[cursor:start])
            pieces.append(mapping.token_for(segment[start:end], kind))
            cursor = end
        pieces.append(segment[cursor:])
        return "".join(pieces)
    return _outside_tokens(text, change, mapping)

# Secrets are the hard line (on a zero-retention rail names may travel, secrets
# never). Any value under a key or label that ends in password, pass, secret, token,
# key, pin, cvv, cvc, code or kode is a SECRET, whatever its length or characters,
# quoted or not: in YAML, INI and env lines (the rest of the line), in JSON, inline
# ("Code: 7319."), and in prose ("die kode is 2580*", "gate code 4471#", "password
# Acorn$2026!"). These run after the labelled rules, so a sort code or a postcode keeps
# its own kind.
# A bare "pass" is a key only with "=" or a quoted value ("PASS: 20 of 20" is a verdict);
# with a prefix ("db_pass", "smtp.pass") it is a key like the others.
# Labels in other words and languages: "memorable word", "mot de passe", "Wachtwoord",
# "Passwort", "PIN-nommer", "key safe", "lockbox".
_MORE_SECRET_LABELS = (r"memorable[ \t]+(?:word|information|answer|name|date|place)|"
                       r"mot[ \t]+de[ \t]+passe|wachtwoord|passwort|kennwort|contrase[ñn]a|senha|"
                       r"key[ \t]*safe|lock[ \t]*box|pin[ \t-]*(?:nommer|nummer|number|no\.?|code)|"
                       r"pwd|passphrase|wagwoord")
_HIDDEN_KEY = (r"(?:" + _MORE_SECRET_LABELS + r"|(?:[A-Za-z0-9]+[_.-])*(?:password|passwd|"
               r"passcode|passphrase|pwd|secret|token|key|apikey|passkey|pin|cvv2?|cvc2?|code|"
               r"kode|wagwoord)|(?:[A-Za-z0-9]+[_.-])+pass|pass(?=[\"']?[ \t]*(?:=|:[ \t]*[\"'])))")
_HIDDEN_LABEL = (r"(?:" + _MORE_SECRET_LABELS + r"|password|passwd|passcode|"
                 r"pin(?:[ \t]*(?:code|number|no\.?))?|cvv2?|cvc2?|(?:[A-Za-z-]+[ \t]+)?code|kode)")
# A secret's digits, written, spaced or read out: "4471#", "1 9 7 3", "four four seven one".
_HIDDEN_DIGIT_WORD = (r"(?:zero|oh|nought|nil|nul|one|een|two|twee|three|drie|four|vier|five|"
                      r"vyf|six|ses|seven|sewe|eight|agt|nine|nege)")
_HIDDEN_DIGITS = (r"(?:\d(?:[ \t-]?\d)*[#*]?|(?:(?:double|triple)[ \t]+)?" + _HIDDEN_DIGIT_WORD
                  + r"(?:[ \t,-]+(?:(?:double|triple)[ \t]+)?" + _HIDDEN_DIGIT_WORD + r"){2,})")
_OPENS_WITH = r"(?:[ \t]+(?:opens|open|unlocks|unlock|works|goes)[ \t]+with)?"
_QUOTED_OR = r"(?P<q>[\"'])?(?P<v>(?(q)(?:(?!(?P=q))[^\n])+|"
_HIDDEN_VALUE_END = r"(?=[.,;:)\]}]*(?:\s|$))"
_SECRET_STOP = {
    "the", "a", "an", "to", "for", "of", "and", "or", "in", "on", "at", "by", "with",
    "not", "now", "here", "there", "below", "above", "attached", "enclosed", "incorrect",
    "wrong", "invalid", "valid", "expired", "required", "needed", "changed", "reset",
    "sent", "same", "case-sensitive", "protected", "strong", "weak", "too", "very",
    "still", "also", "being", "ready", "set", "it", "this", "that", "your", "my", "our",
    "their", "his", "her", "empty", "blank", "missing", "unknown", "different", "correct",
    "ok", "fine", "simple", "easy", "hard", "long", "short", "secure", "safe", "private",
    "confidential", "shown", "given", "printed", "written", "case", "ek", "die", "nie",
    "jou", "which", "what", "who", "where", "when", "how", "mine", "yours", "ours",
    "theirs", "one", "name", "number", "these", "those", "everything", "nothing", "all",
}


def _secret_word_check(text):
    """A spoken value is a secret unless it is an ordinary word of a sentence."""
    word = text.strip("\"'").lower()
    return None if word in _SECRET_STOP else (0, len(text))


_SECRET_POSITIONS = (
    # A YAML, INI or env line: the rest of the line, quoted or not, a trailing comment off.
    _Rule("SECRET", _rx(
        r"(?im)^[ \t]*(?:[-*][ \t]+)?[\"']?" + _HIDDEN_KEY + r"[\"']?[ \t]*[:=][ \t]*"
        + _QUOTED_OR + r"[^\s\"'#](?:(?![.!?][ \t]+\S)[^\n])*?))(?(q)(?P=q))[ \t]*"
        r"(?:[ \t]#[^\n]*)?$"), group="v"),
    # A label alone on its line, its value the whole next line: "Password:" over "Kx9#mq",
    # "Door code" over "1973". Not when the next line is a label of its own.
    _Rule("SECRET", _rx(
        r"(?im)^[ \t]*(?:[-*#>][ \t]*)*(?:" + _HIDDEN_KEY + r"|" + _HIDDEN_LABEL + r")[ \t]*[:=#-]?"
        r"[ \t]*\n[ \t]*(?P<v>(?![^\n]{0,40}:[ \t])\S[^\n]{0,80}?)[ \t]*$"), group="v"),
    # JSON: "cvv": "731", "pin": 4417.
    _Rule("SECRET", _rx(
        r"(?i)\"" + _HIDDEN_KEY + r"\"[ \t]*:[ \t]*(?:\"(?P<v>(?:[^\"\\\n]|\\.)+)\"|(?P<n>-?[\w.+-]+))"),
        groups=(("v", "SECRET"), ("n", "SECRET"))),
    # Inline: "Code: 7319.", "password=hunter2", "PIN: 4417 2290#", "Wachtwoord: Kx9#mq".
    _Rule("SECRET", _rx(
        r"(?i)(?<![\w-])" + _HIDDEN_KEY + r"[ \t]*[:=][ \t]*" + _QUOTED_OR +
        r"(?:" + _HIDDEN_DIGITS + r"|[^\s\"'<>]+?)))(?(q)(?P=q))" + _HIDDEN_VALUE_END), group="v"),
    # Prose with "is": "die kode is 2580*", "my PIN-nommer is 7391".
    _Rule("SECRET", _rx(
        r"(?i)(?<![\w-])" + _HIDDEN_LABEL + r"[ \t]+(?:is|was|are|=|-)[ \t]+(?:now[ \t]+)?"
        + _QUOTED_OR + r"(?:" + _HIDDEN_DIGITS + r"|[^\s\"'<>]+?)))(?(q)(?P=q))" + _HIDDEN_VALUE_END),
        group="v", check=_secret_word_check),
    # A bare label and a value with a digit or a symbol, written, spaced or read out:
    # "gate code 4471#", "key safe 1973", "the key safe opens with 1 9 7 3".
    _Rule("SECRET", _rx(
        r"(?i)(?<![\w-])" + _HIDDEN_LABEL + _OPENS_WITH + r"[ \t]+(?P<v>" + _HIDDEN_DIGITS + r"|"
        r"(?=[^\s]*[\d#*!$%&@?])[^\s\"'<>]+?)" + _HIDDEN_VALUE_END), group="v"),
    # Best effort, not the hard line: a value before its label ("4821 is my PIN") and the
    # digits on the back of a card ("the 3 digit code on the back is 417").
    _Rule("SECRET", _rx(
        r"(?i)(?<![\w-])(?P<v>" + _HIDDEN_DIGITS + r"|[^\s\"'<>]+)[ \t]+(?:is|was)[ \t]+"
        r"(?:my|the|our|your|his|her|their)[ \t]+(?:[A-Za-z-]+[ \t]+){0,2}?(?:" + _HIDDEN_LABEL
        + r")\b"), group="v", check=_secret_word_check),
    _Rule("SECRET", _rx(
        r"(?i)\b(?:\d|three|four|six)[ \t-]*digits?\b(?:[ \t]+(?:code|number|pin))?[^\n.;]{0,40}?"
        r"\b(?:is|are|:|=)[ \t]+(?P<v>\d(?:[ \t]?\d){2,5})\b"), group="v"),
)

# A table or CSV column headed by a secret's label: every value in it is a SECRET.
_COLUMN_LABEL = re.compile(r"(?i)\A[*_ \t\"']*(?:" + _HIDDEN_KEY + r"|" + _HIDDEN_LABEL
                           + r")[*_ \t:\"']*\Z")
_TABLE_RULE = re.compile(r"[ \t|:-]*-{2,}[ \t|:-]*\Z")


def _field_spans(line, delimiter):
    spans, start = [], 0
    for index, char in enumerate(line):
        if char == delimiter:
            spans.append((start, index))
            start = index + 1
    spans.append((start, len(line)))
    return spans


def _secret_columns(line, delimiter):
    return [i for i, (s, e) in enumerate(_field_spans(line, delimiter))
            if _COLUMN_LABEL.match(line[s:e])]


def secret_column_spans(view):
    """The (start, end) of every cell under a secret column header, in a markdown table
    or a CSV, TSV or semicolon table. Used by hush to code the cells and by the residual
    check to refuse any that survive."""
    rows = view.split("\n")
    offsets, position = [], 0
    for row in rows:
        offsets.append(position)
        position += len(row) + 1
    spans, i = [], 0

    def take(row, base, delimiter, columns):
        fields = _field_spans(row, delimiter)
        for column in columns:
            if column < len(fields):
                start, end = _strip_span(row, *fields[column])
                if start < end:
                    spans.append((base + start, base + end))

    while i < len(rows):
        row = rows[i]
        if "|" in row and i + 1 < len(rows) and _TABLE_RULE.match(rows[i + 1]):
            columns = _secret_columns(row, "|")
            j = i + 2
            while j < len(rows) and "|" in rows[j] and rows[j].strip():
                if columns:
                    take(rows[j], offsets[j], "|", columns)
                j += 1
            i = j
            continue
        for delimiter in ("\t", ",", ";"):
            if delimiter not in row:
                continue
            columns = _secret_columns(row, delimiter)
            if not columns:
                continue
            j = i + 1
            while j < len(rows) and rows[j].strip() and rows[j].count(delimiter) >= max(columns):
                take(rows[j], offsets[j], delimiter, columns)
                j += 1
            if j > i + 1:
                i = j - 1
                break
        i += 1
    return spans


def _scrub_columns(text, mapping):
    """Code every cell of a secret column, before any other rule reads the table."""
    view = _view(text)
    issued = mapping.issued()
    pieces, cursor = [], 0
    for start, end in sorted(secret_column_spans(view)):
        cell = text[start:end]
        if start < cursor or any(m.group(0) in issued for m in TOKEN.finditer(cell)):
            continue
        pieces.append(text[cursor:start])
        pieces.append(mapping.token_for(cell, "SECRET"))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)

# Labelled: the field names itself, so the value is taken at its word. Format checks
# are for finding the unlabelled ones. These run before the shapes, which is what
# keeps a 13-digit ID from being filed as a card, and before the name guess, which is
# what keeps a label from being taken for a person.
_LABELLED = (
    _Rule("SECRET", _rx(
        r"(?i:\b(?:api[_ -]?key|apikey|access[_ -]?key|secret(?:[_ -]?key)?|"
        r"client[_ -]?secret|password|passwd|passcode|pwd|auth[_ -]?token|"
        r"access[_ -]?token|token)\b)[ \t]*[:=][ \t]*(?:\n[ \t]*)?[\"']?"
        r"([^\s\"'<>]{7,}[^\s\"'<>.,;:])"), group=1),
    _Rule("SECRET", _rx(
        r"(?i:\b(?:password|passwd|passcode)\b)[ \t]+is[ \t]+[\"']?"
        r"((?=[A-Za-z0-9_./+=~-]*[\d_/+=~])[A-Za-z0-9_./+=~-]{5,}[A-Za-z0-9_/+=~-])"), group=1),
    _Rule("SECRET", _rx(r"(?i:\bbearer)[ \t]+([A-Za-z0-9_./+=~-]{16,})"), group=1),
    # A key named and then given with only a space: the value carries a digit or an
    # underscore and is long, which is what a key looks like and a word does not.
    _Rule("SECRET", _rx(
        r"(?i:\b(?:api[_ -]?key|apikey|access[_ -]?key|secret[_ -]?key|client[_ -]?secret|"
        r"auth[_ -]?token|access[_ -]?token)\b)[ \t]+"
        r"((?=[A-Za-z0-9_./+=~-]*[\d_])[A-Za-z0-9_./+=~-]{12,})"), group=1),
    _Rule("HANDLE", _rx(
        r"(?i:\b(?:handle|username|user[ \t]*name|login|user[ \t]*id|screen[ \t]*name)\b)"
        + _GAP + r"(@?[A-Za-z0-9_][A-Za-z0-9_.-]{1,30}[A-Za-z0-9_])(?![\w@])"), group=1,
        context=_handle_context),
    _Rule("SECRET", _rx(
        r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{16,}|glpat-[A-Za-z0-9_-]{16,}|"
        r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}|"
        r"xox[baprs]-[A-Za-z0-9-]{10,})")),
    _Rule("SECRET", _rx(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----")),
    _Rule("SECRET", _rx(
        r"(?i:\b(?:pin(?:[ \t]*(?:code|number|no\.?))?|cvv2?|cvc2?|security[ \t]+code)\b)"
        + _GAP + r"(\d(?:[ \t-]?\d){2,11}[#*]?)(?!\d)"), group=1),
    _Rule("NHSNUM", _rx(
        r"(?i:\bNHS[ \t]*(?:number|no\.?|num|#))" + _NEAR + r"(?<![A-Za-z0-9-])(" + _TEN_DIGITS + r")"
        + _NO_MORE_DIGITS), group=1, pack="uk"),
    _Rule("NHSNUM", _rx(
        r"(?i:\bNHS\b)" + _GAP + r"(" + _TEN_DIGITS + r")" + _NO_MORE_DIGITS), group=1, pack="uk"),
    _Rule("NINO", _rx(
        r"(?i:\b(?:national[ \t]*insurance(?:[ \t]*(?:no\.?|number))?|"
        r"ni[ \t]*(?:no\.?|number)|nino|ni)\b)" + _GAP +
        r"((?i:[A-Z]{2}(?:[ \t-]?\d{2}){3}[ \t-]?[A-D]?|[A-Z]{2}[ \t-]?\d{6}[ \t-]?[A-D]?))"
        r"(?![A-Za-z0-9])"), group=1, pack="uk"),
    _Rule("NINO", _rx(
        r"(?i:\b(?:national[ \t]*insurance(?:[ \t]*(?:no\.?|number))?|"
        r"ni[ \t]*(?:no\.?|number)|nino)\b)" + _GAP +
        r"((?=[A-Z0-9 ]*\d)[A-Z0-9][A-Z0-9 ]{4,11}[A-Z0-9])(?![A-Za-z0-9])"), group=1, pack="uk"),
    _Rule("PASSPORT", _rx(
        r"(?i:\bpassport\b(?:[ \t]*(?:no\.?|number|num|#))?)" + _GAP +
        r"((?=[A-Z]{0,3}\d)[A-Z0-9]{6,9})(?![A-Za-z0-9])"), group=1),
    _Rule("LICENCE", _rx(
        r"(?i:\bdriving[ \t]*licen[cs]e\b(?:[ \t]*(?:no\.?|number))?)" + _GAP +
        r"((?=[A-Z0-9]*\d)[A-Z0-9]{8,18})(?![A-Za-z0-9])"), group=1),
    _Rule("BIC", _rx(
        r"(?i:\b(?:BIC|SWIFT(?:[ \t]*code)?)\b)" + _GAP +
        r"([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)(?![A-Za-z0-9])"), group=1),
    _Rule("SORTCODE", _rx(
        r"(?i:\b(?:sort[ \t-]*code|s/c)\b)" + _NEAR + r"(?<![A-Za-z0-9-])(" + _SORT_VALUE + r")"
        + _NO_MORE_DIGITS), group=1, pack="uk"),
    _Rule("IBAN", _rx(
        r"(?i:\b(?:iban|account(?:[ \t]*(?:no\.?|number))?|acct)\b)" + _GAP +
        r"((?i:[a-z]{2}\d{2}(?:[ \t]?[a-z0-9]{4}){2,7}(?:[ \t]?[a-z0-9]{1,4})?))(?![A-Za-z0-9])"),
        group=1),
    _Rule("ACCOUNTNO", _rx(
        r"(?i:\b(?:account|acct|acc|a/c)\b(?![-/])\.?[ \t]*(?:no\.?|number|num|#))" + _GAP +
        r"(?<![A-Za-z0-9-])(\d{4}" + _GS + r"?\d{4}|\d{6,10})" + _NO_MORE_DIGITS), group=1),
    # A UK account number is eight digits; "near" is within a short phrase of the cue.
    _Rule("ACCOUNTNO", _rx(
        r"(?i:\b(?:account|acct|acc|a/c)\b(?![-/]))" + _NEAR + r"(?<![A-Za-z0-9-])(\d{8}|\d{4}" + _GS + r"\d{4})"
        + _NO_MORE_DIGITS), group=1, pack="uk"),
    # A sort code beside an eight-digit number is a bank account, cue or no cue.
    _Rule("SORTCODE", _rx(
        r"(?<![\d.-])(\d{2}-\d{2}-\d{2})[ \t,/|;]{1,4}(\d{8})(?!\d)"),
        groups=((1, "SORTCODE"), (2, "ACCOUNTNO")), pack="uk"),
    _Rule("CARD", _rx(
        r"(?i:\b(?:card|visa|mastercard|amex|debit[ \t]+card|credit[ \t]+card)\b"
        r"(?:[ \t]*(?:no\.?|number|num|#))?)" + _GAP +
        r"((?:\d(?:[ \t]{1,3}|[.-]|[ \t]*\n[ \t]*)?){12,18}\d)(?!\d)"), group=1),
    _Rule("MRN", _rx(
        r"(?i:\b(?:MRN|hospital[ \t]+(?:number|no\.?|id)|patient[ \t]+(?:id|number|no\.?)|"
        r"unit[ \t]+number|chi[ \t]+(?:number|no\.?))\b)" + _GAP +
        r"((?=[\w-]*\d)[\w-]{4,}(?:[ \t]{1,2}[\w-]*\d[\w-]*)*)"), group=1),
    # The clinical shape ("01/01/2000"), the document shape ("01 January 2000") and the
    # words a letter uses ("born on 1 February 1980").
    _Rule("DOB", _rx(
        r"(?i:\b(?:DOB|D\.O\.B\.?|date[ \t]*of[ \t]*birth|birth[ \t]*date|born(?:[ \t]+on)?)\b\.?)"
        + _GAP + r"(" + _DATE_VALUE + r")\b"), group=1),
    _Rule("PHONE", _rx(
        r"(?i:\b(?:tel|telephone|phone|mobile|mob|cell|fax|landline|whatsapp)\b\.?)" + _GAP +
        r"((?:\+|\(?\d)[\d \t().\n-]{7,22}\d(?!\d)" + _EXT + r")"),
        group=1, check=_with_extension(_labelled_phone_check)),
    # A vehicle registration after its label is a code.
    _Rule("CODE", _rx(
        r"(?i:\b(?:reg(?:istration)?(?:[ \t]*(?:no\.?|number|mark|plate))?|vrm|number[ \t]+plate|"
        r"vehicle[ \t]+reg(?:istration)?)\b)" + _GAP +
        r"((?=[A-Z0-9 ]*\d)[A-Z0-9]{2,4}[ \t]?[A-Z0-9]{3,4})(?![A-Za-z0-9])"), group=1),
    _Rule("POSTCODE", _rx(
        r"(?i:\b(?:post(?:al)?[ \t-]*code|zip(?:[ \t-]*code)?|code[ \t]+postal)\b)"
        r"(?:[ \t]+(?:of|is))?" + _GAP +
        r"(\d{4,6}(?:-\d{4}|[ \t]?[A-Z]{2}(?![A-Za-z]))?|[A-Z]\d[A-Z][ \t-]?\d[A-Z]\d)(?![\w-])"),
        group=1),
    _Rule("POSTCODE", _rx(
        r"(?i:\b(?:post(?:al)?[ \t-]*code|zip[ \t]*code))\b" + _GAP +
        r"((?:[A-Z0-9]{1,4}|(?i:" + _SPELLED + r"))(?:[ \t,]+(?:[A-Z0-9]{1,4}|(?i:"
        + _SPELLED + r"))){1,7})(?![\w])"), group=1, check=_postcode_label_check),
) + _SECRET_POSITIONS

# Labelled only, because their values are free text: a South African ID number after its
# label, and an address after a "Home address:" label (the colon makes it a field, so
# "your home address for the form" stays prose).
_DOCUMENT_LABELLED = (
    _Rule("SAID", _rx(
        r"\b(?:(?:south\s*african\s*)?id\s*(?:no|number)?)[:\s#]*(\d{13})\b", re.I), group=1,
        pack="south-africa"),
    _Rule("HOMEADDR", _rx(
        r"\b(?:home|residential|postal)[ \t]*address[ \t]*:[ \t]*([^\n;|]{8,120})", re.I),
        group=1),
)

_STREET_TYPES = (r"Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Close|Court|Ct|Way|"
                 r"Terrace|Place|Crescent|Gardens?|Grove|Mews|Square|Row|Walk|Rise|"
                 r"Parade|Hill|Wharf|Quay|Yard|Cottages?|Villas?|Wynd|Brae|Gate|Vale|"
                 r"Green|Park|View|Fields?|Meadows?|Chase|Croft|Mead|Boulevard|Circus|"
                 r"Embankment|Broadway")

# Words that follow a number in prose far more often than a street name does.
_NOT_A_STREET = (r"minutes?|mins?|hours?|hrs?|seconds?|miles?|km|kilometres?|metres?|"
                 r"meters?|yards?|feet|foot|days?|weeks?|months?|years?|times?|people|"
                 r"cars?|lanes?|ways?|of|the|a|an|more|other|or|and|to|in|on|at|by|"
                 r"down|up|along|off|from|for|per|percent|pounds?|quid")

# Software versions are not dates, addresses or numbers: "v1.2.10", "iOS 17.4.1".
_VERSION_CUE = re.compile(
    r"(?i)(?:\bv|\bver\.?|\bversion|\bbuild|\brelease|\bfirmware|\bupdate|\bupgrade|\bpatch|"
    r"\bios|\bipados|\bandroid|\bchrome|\bfirefox|\bsafari|\bedge|\bwindows|\bmacos|\bpython|"
    r"\bnode|\bapp|\bkernel|\blinux|\bubuntu|\bdebian|\bsoftware|\bsw|\bfw|\bdriver|"
    r"\bbios)[ \t:]*v?\Z")
_CURRENCY_BEFORE = re.compile(r"(?:[£$€¥][ \t]?-?|(?i:\b(?:gbp|usd|eur)[ \t]?))\Z")


def _not_a_version(view, start, end):
    return not _VERSION_CUE.search(view[max(0, start - 20):start])


def _not_money_or_version(view, start, end):
    return _not_a_version(view, start, end) and not _CURRENCY_BEFORE.search(
        view[max(0, start - 6):start])


# Month names in English and in other languages letters come in: Afrikaans,
# Dutch, German, French, Spanish ("1 Januarie 1980", "17 Mei 1990", "3 Oktober 1979").
_MONTH_NAMES = (
    "january", "jan", "februari", "february", "feb", "march", "mar", "april", "apr", "may",
    "june", "jun", "july", "jul", "august", "aug", "september", "sept", "sep", "october",
    "oct", "november", "nov", "december", "dec",
    "januarie", "februarie", "maart", "mei", "junie", "julie", "augustus", "oktober",
    "desember", "januari", "juni", "juli", "januar", "februar", "märz", "marz", "mai",
    "dezember", "janvier", "février", "fevrier", "mars", "avril", "juin", "juillet",
    "août", "aout", "septembre", "octobre", "novembre", "décembre", "decembre", "enero",
    "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "octubre", "noviembre", "diciembre",
)
_MONTH = ("(?:" + "|".join(sorted(set(_MONTH_NAMES), key=len, reverse=True)) + r")(?![a-zà-ÿ])")
_ORDINAL_WORD = (r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|"
                 r"twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|"
                 r"nineteenth|twentieth|thirtieth|(?:twenty|thirty)[- ](?:first|second|third|"
                 r"fourth|fifth|sixth|seventh|eighth|ninth))")
_UNITS_WORD = r"(?:one|two|three|four|five|six|seven|eight|nine)"
_TEENS_WORD = (r"(?:ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
               r"nineteen)")
_TENS_WORD = r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
_YEAR_SPOKEN = (r"(?:(?:nineteen|twenty)[- ](?:hundred|oh[- ]" + _UNITS_WORD + r"|" + _TEENS_WORD
                + r"|" + _TENS_WORD + r"(?:[- ]" + _UNITS_WORD + r")?)|two[- ]thousand(?:[- ]and)?"
                r"(?:[- ](?:" + _TEENS_WORD + r"|" + _TENS_WORD + r"(?:[- ]" + _UNITS_WORD + r")?|"
                + _UNITS_WORD + r"))?)")


def _numeric_date_check(text):
    parts = re.findall(r"\d+", text)
    first, second, year = (int(p) for p in parts[:3])
    if len(parts[2]) == 4 and not 1900 <= year <= 2099:
        return None
    if (1 <= first <= 31 and 1 <= second <= 12) or (1 <= first <= 12 and 1 <= second <= 31):
        return 0, len(text)
    return None


def _iso_date_check(text):
    _year, month, day = (int(p) for p in re.findall(r"\d+", text)[:3])
    return (0, len(text)) if 1 <= month <= 12 and 1 <= day <= 31 else None


# A dose or a measure is medicine, not a code: "1000mg", "2x500mg", "120mmHg", "10mg/kg".
_UNIT = (r"(?:mg|mcg|µg|ug|g|kg|ng|ml|l|dl|mmol|umol|mol|iu|units?|mmhg|cm|mm|km|m|kcal|"
         r"cal|hrs?|h|mins?|secs?|s|am|pm|x|bpm|ppm|mph|kph|gb|mb|kb|tb|ghz|mhz|hz|w|kw|kwh|"
         r"v|mah|k|p|yrs?|y|wks?|d)")
_MEASURE = re.compile(r"(?i)\d+(?:[.,]\d+)?(?:x\d+(?:[.,]\d+)?)?" + _UNIT
                      + r"(?:/" + _UNIT + r")?\Z|\d+(?:st|nd|rd|th)\Z|\d+x\d+\Z")


def _code_check(text):
    """A word of six or more letters and digits with two digits or more is a code:
    a hospital number, a licence, a reference, a key. A dose, an ordinal or a clinical
    word with digits (KEEP) is not. Digit groups after a code ending in a digit, and a
    one or two letter capital suffix after a code with four digits, go with it."""
    parts = re.fullmatch(r"(\S+)((?:[ \t]\d{2,})*)([ \t][A-Z]{1,2})?", text)
    core, tail, suffix = parts.group(1), parts.group(2), parts.group(3) or ""
    taken = _code_core_check(core)
    if taken is None:
        return None
    end = len(core)
    if tail and core[-1].isdigit():
        end += len(tail)
        if suffix and sum(c.isdigit() for c in core + tail) >= 4 and \
                suffix.strip().lower() not in keep_words() | _FORM_WORDS:
            end += len(suffix)
    elif not tail and suffix and sum(c.isdigit() for c in core) >= 4 and \
            suffix.strip().lower() not in keep_words() | _FORM_WORDS:
        end += len(suffix)
    return 0, end


def _code_core_check(text):
    alnum = re.sub(r"[^A-Za-z0-9]", "", text)
    if len(alnum) < 6 or sum(c.isdigit() for c in alnum) < 2 or not re.search(r"[A-Za-z]", alnum):
        return None
    if text.lower() in keep_words() or _MEASURE.match(text):
        return None
    if all(_MEASURE.match(p) or (p.isdigit() and len(p) <= 4) for p in re.split(r"[-/]", text) if p):
        return None
    return 0, len(text)


def _year_range(text):
    return re.fullmatch(r"(?:19|20)\d{2}[ \t]*[/-][ \t]*(?:(?:19|20)\d{2}|\d{2})", text)


def _number_check(text):
    """Six digits or more, however grouped, is a number to code out, unless it is a
    tax-year range ("2026/27")."""
    if sum(c.isdigit() for c in text) < 6 or _year_range(text):
        return None
    return 0, len(text)


def _folded_number_check(text):
    """As `_number_check`, for a run over a line fold, which is taken only when no group
    is a decimal amount, so a column of prices is not joined into one number."""
    if "\n" in text and re.search(r"\d\.\d{1,2}(?!\d)", text):
        return None
    return _number_check(text)


# Between digit groups for the catch-all: up to three spaces, a dot, dash or slash, or
# a line fold.
_NUMBER_JOIN = r"(?:[ \t]{1,3}|[ \t]*[./-][ \t]*|[ \t]*\n[ \t]*)"
_NUMBER_JOIN_LINE = r"(?:[ \t]{1,3}|[ \t]*[./-][ \t]*)"
_NUMBER_START = r"(?<![\w.,/-])(?<!\w[.,/-])"
_NUMBER_END = r"(?!\w)(?![.,/-]\d)"

# The default for the personal and health classes, added after an out-of-sample
# tester found that a value with no label hush knew went through (CSV
# columns, statement rows, table headers): every full date, every code that mixes
# letters with digits and every run of six digits or more is coded out, label or not.
# The labelled rules and the shapes above them run first and set the kind; these take
# what is left, as DATE, CODE and NUMBER. Restore puts every one back exactly.
_SPACED_SHAPES = (
    # A UK driving licence spaced out ("MCTAG 812240 C9 9XK"), before the postcode rule
    # can take its tail, and an NI number with every character spaced.
    _Rule("LICENCE", _rx(
        r"(?i)\b[A-Z9]{5}[ \t-]?\d{6}[ \t-]?[A-Z9]{2}[ \t-]?\d[ \t-]?[A-Z]{2}\b"), pack="uk"),
    _Rule("NINO", _rx(
        r"(?i)\b[A-CEGHJ-PR-TW-Z][ \t]{1,3}[A-CEGHJ-NPR-TW-Z](?:[ \t]{1,3}\d){6}[ \t]{1,3}[A-D]\b"),
        pack="uk"),
)
_CATCH_ALL = (
    # A code keeps the digit groups that follow it ("D4/7718 2290") and a short capital
    # suffix ("CHB01234567 AB"): a long number keeps no trailing group.
    _Rule("CODE", _rx(
        r"(?<![\w/.@-])(?=[A-Za-z0-9_/.-]*\d)[A-Za-z0-9](?:[A-Za-z0-9_/.-]*[A-Za-z0-9])?"
        r"(?![\w@])(?![/.-][A-Za-z0-9])"
        r"(?:[ \t]\d{2,}(?![\w/-])(?![.]\d))*(?:[ \t][A-Z]{1,2}(?![\w/-])(?!\.\w))?"),
        check=_code_check, context=_not_a_version),
)

# A run of digit groups for the number pass. A comma before it is a field separator
# when four digits or more follow ("02/10/2026,279860"), and a thousands separator when
# three do ("1,203.11"), which is an amount and stays.
_NUMBER_RUN = re.compile(
    r"(?<![\w.])(?<!\w[./-])(?:(?<!\d,)|(?=\d{4}))\d+(?:" + _NUMBER_JOIN + r"\d+)*"
    r"(?!\w)(?![./-]\d)")
_RANGE = re.compile(r"\d{1,3}[ \t]*-[ \t]*\d{1,3}\Z")
_AMOUNT = re.compile(r"\d+\.\d{2}\Z")
_LETTER_PREFIX = re.compile(r"(?<![\w])([A-Z]{1,3})[ \t]\Z")


def _number_parts(view, start, end):
    """The stretches of one run between its amounts: "42.18" stands alone, so a store
    number and a price side by side never join into one long number."""
    parts, current = [], None
    for item in re.finditer(r"\S+", view[start:end]):
        if _AMOUNT.match(item.group(0)):
            if current:
                parts.append(current)
            current = None
            continue
        span = (start + item.start(), start + item.end())
        current = span if current is None else (current[0], span[1])
    if current:
        parts.append(current)
    return parts


# A number read out word by word, in English or Afrikaans, with "double" and "triple":
# "oh seven seven double oh, nine double oh, three two seven", "twee oh, vier vyf".
_DIGIT_WORDS = {"zero": 1, "oh": 1, "nought": 1, "nil": 1, "nul": 1, "one": 1, "een": 1,
                "two": 1, "twee": 1, "three": 1, "drie": 1, "four": 1, "vier": 1, "five": 1,
                "vyf": 1, "six": 1, "ses": 1, "seven": 1, "sewe": 1, "eight": 1, "agt": 1,
                "nine": 1, "nege": 1}
_REPEATS = {"double": 2, "dubbel": 2, "triple": 3, "trippel": 3}
_SPOKEN_DIGIT = "(?:" + "|".join(sorted(_DIGIT_WORDS, key=len, reverse=True)) + ")"
_SPOKEN_REPEAT = "(?:" + "|".join(_REPEATS) + ")"
# "nine hundred" stands for 900 inside a run, as phone numbers are read in the UK.
_SPOKEN_ONE = _SPOKEN_DIGIT + r"(?:[ \t]+hundred)?"
# Between two digit words: spaces, commas, dots or dashes, and the fillers of speech
# ("oh seven seven, um, double oh").
_SPOKEN_FILLER = r"(?:uh|uhm|um|umm|er|erm|ah|hm|hmm|mm)"
_SPOKEN_GAP = r"[ \t,.-]+(?:" + _SPOKEN_FILLER + r"[ \t,.-]+)*"
_SPOKEN_RUN = re.compile(
    r"(?i)(?<![\w])(?:(?-i:[A-Z])[ \t]+){0,3}(?:plus[ \t]+)?(?:" + _SPOKEN_REPEAT + r"[ \t]+)?"
    + _SPOKEN_ONE + r"(?:" + _SPOKEN_GAP + r"(?:" + _SPOKEN_REPEAT + r"[ \t]+)?" + _SPOKEN_ONE
    + r"){2,}(?![\w])")


def _spoken_digits(run):
    count, times = 0, 1
    for word in re.findall(r"[A-Za-z]+", run):
        low = word.lower()
        if low in _REPEATS:
            times = _REPEATS[low]
        elif low == "hundred":
            count += 2
        elif low in _DIGIT_WORDS:
            count += times
            times = 1
    return count


def _scrub_spoken(text, mapping):
    """Six digits or more read out as words become one token: PHONE when it starts with
    oh or zero and has ten or eleven digits, NUMBER otherwise."""
    def change(segment):
        pieces, cursor = [], 0
        for match in _SPOKEN_RUN.finditer(segment):
            digits = _spoken_digits(match.group(0))
            if digits < 6:
                continue
            first = re.search(r"(?i)\b(?:zero|oh|nul|nought)\b", match.group(0)[:12])
            kind = "PHONE" if first and 10 <= digits <= 11 else "NUMBER"
            pieces.append(segment[cursor:match.start()])
            pieces.append(mapping.token_for(match.group(0), kind))
            cursor = match.end()
        pieces.append(segment[cursor:])
        return "".join(pieces)
    return _outside_tokens(text, change, mapping)


def _scrub_numbers(text, mapping):
    """Every run of six digits or more, label or not, as NUMBER: grouped by spaces, dots,
    dashes, slashes or a line fold, with a scan's O and l read as digits. Money after a
    currency sign, a tax-year range and a software version stay. A short capital prefix
    goes with the number ("HN 047 2913")."""
    def change(segment):
        view = _ocr_digits(_view(segment))
        spans = []
        for match in _NUMBER_RUN.finditer(view):
            for start, end in _number_parts(view, match.start(), match.end()):
                run = view[start:end]
                prefix = _LETTER_PREFIX.search(view[max(0, start - 4):start])
                # A range ("130-180", "pages 112-118") stays, unless letters lead it, as
                # in a registration ("CA 123-456").
                if (sum(c.isdigit() for c in run) < 6 or _year_range(run)
                        or (_RANGE.match(run) and not prefix)
                        or not _not_money_or_version(view, start, end)):
                    continue
                if prefix and prefix.group(1).lower() not in keep_words() | _FORM_WORDS:
                    start -= len(prefix.group(0))
                spans.append((start, end))
        pieces, cursor = [], 0
        for start, end in spans:
            if start < cursor:
                continue
            pieces.append(segment[cursor:start])
            pieces.append(mapping.token_for(segment[start:end], "NUMBER"))
            cursor = end
        pieces.append(segment[cursor:])
        return "".join(pieces)
    return _outside_tokens(text, change, mapping)

# A weekday before a date and a time after it go with the date: "Fri, 15 Dec 2023",
# "2025-01-08T14:31:17Z", "08/15/2023 19:45", "14 March 2024 at 10:30".
_WEEKDAY = (r"(?:(?-i:(?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs?)?|Fri|Sat(?:ur)?|Sun)(?:day)?)\.?,?"
            r"[ \t]+)?")
_CLOCK = (r"(?:\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[ \t]?[AaPp]\.?[Mm]\.?(?!\w))?"
          r"|\d{1,2}[ \t]?[AaPp]\.?[Mm]\.?(?!\w))"
          r"(?:Z|[ \t]?(?:[+-]\d{2}:?\d{2}|UTC|GMT|BST|CET|EST|EDT|PST|PDT)(?!\w))?")
_TIME_AFTER = r"(?:(?:T|,?[ \t]+(?:at[ \t]+)?)" + _CLOCK + r")?"
# English month names, capitalised, for dates written without a year: "March 3rd",
# "3rd of March", "October 2023". Lower case "march" and "may" are verbs.
_MONTH_EN = (r"(?-i:(?:January|February|March|April|May|June|July|August|September|October|"
             r"November|December|(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?))"
             r"(?![a-z])(?!['’]s\b)")
# A plain day and month need a word after them that reads as a date ("15 March, at ...",
# "15 March and"), not a noun ("12 June bugs").
_DATE_FOLLOWS = (r"(?![ \t]+(?!(?:at|and|or|to|is|was|will|until|till|through|the|from|for|"
                 r"when|in|on|by|this|next|last)\b)[a-z])")

# Every full date, in every shape a letter or a form uses: "03/07/1981", "9/1/2019",
# "1990-04-17", "03-Jul-1981", "3rd July 1981", "February 14, 1975". Coded out as DATE
# tokens rather than shifted, because restore then puts back the real date exactly; a
# shifted date a model rewrites would come back wrong and look right.
_DATES = (
    _Rule("DATE", _rx(
        r"(?<![\w./-])" + _WEEKDAY + r"\d{1,2}[ \t]*([/.-])[ \t]*\d{1,2}[ \t]*\1[ \t]*"
        r"(?:(?:19|20)\d{2}|\d{2})(?!\w)(?![/.-]\d)" + _TIME_AFTER),
        check=_numeric_date_check, context=_not_a_version, ocr=True),
    _Rule("DATE", _rx(r"(?<![\w./-])(?:19|20)\d{2}([/.-])\d{1,2}\1\d{1,2}(?![\d/.-]\d)(?!\d)"
                      + _TIME_AFTER),
          check=_iso_date_check, context=_not_a_version, ocr=True),
    _Rule("DATE", _rx(
        r"(?i)(?<!\w)" + _WEEKDAY + r"\d{1,2}(?:st|nd|rd|th)?[ \t]*(?:of[ \t]+)?-?" + _MONTH +
        r"\.?[ \t,-]*(?:(?:19|20)\d{2}(?!\d)|" + _YEAR_SPOKEN + r"\b)" + _TIME_AFTER)),
    # A date read out: "the fourteenth of March nineteen eighty four".
    _Rule("DATE", _rx(
        r"(?i)\b" + _ORDINAL_WORD + r"(?:[ \t]+of)?[ \t]+" + _MONTH + r"[ \t,]+(?:(?:19|20)\d{2}(?!\d)|"
        + _YEAR_SPOKEN + r"\b)")),
    _Rule("DATE", _rx(
        r"(?i)(?<!\w)" + _WEEKDAY + _MONTH + r"\.?[ \t]+\d{1,2}(?:st|nd|rd|th)?,?[ \t]+"
        r"(?:19|20)\d{2}(?!\d)" + _TIME_AFTER)),
    # A month and a year: "October 2023", "March of 2024".
    _Rule("DATE", _rx(
        r"(?<!\w)" + _MONTH_EN + r",?[ \t]+(?:of[ \t]+)?(?:19|20)\d{2}(?![\d.,:/-]\d|\d)")),
    # A date with no year: "March 3rd", "Tuesday, March 3rd", "3rd of March", "15 March",
    # "fourteenth of March".
    _Rule("DATE", _rx(
        r"(?<!\w)" + _WEEKDAY + _MONTH_EN + r"[ \t]+(?:the[ \t]+)?\d{1,2}(?:st|nd|rd|th)?"
        r"(?![\w%:]|[.,/-]\d|[ \t]*[-/][ \t]*\d)" + _TIME_AFTER)),
    _Rule("DATE", _rx(
        r"(?<![\w./-])" + _WEEKDAY + r"(?:\d{1,2}(?:st|nd|rd|th)[ \t]*(?:of[ \t]+)?"
        r"|\d{1,2}[ \t]+of[ \t]+)" + _MONTH_EN + _TIME_AFTER)),
    _Rule("DATE", _rx(
        r"(?<![\w./-])" + _WEEKDAY + r"\d{1,2}[ \t]+" + _MONTH_EN + _DATE_FOLLOWS
        + _TIME_AFTER)),
    _Rule("DATE", _rx(
        r"(?i:\b" + _ORDINAL_WORD + r")[ \t]+of[ \t]+" + _MONTH_EN)),
)

# A year on its own, off by default ("years" in a config's [dates]): "near" takes one
# after a word that dates it ("born in 1985", "since 1999", "class of 2010"), "all" takes
# every 1900 to 2099 that is not money, a version or part of a run of digit groups.
_YEAR_CUE = (r"(?i:\b(?:in|since|until|till|by|from|during|circa|around|before|after|born|"
             r"graduated|married|died|moved|joined|started|left|retired|class[ \t]+of|year)"
             r"(?:[ \t]+(?:in|the|of|early|late|mid|summer|winter|spring|autumn|fall))*"
             r"[ \t,]+)")
_YEAR_BODY = r"((?:19|20)\d{2})(?![\w%]|[.,:/-]\d)(?![ \t]\d)"
_YEARS = {
    "near": _Rule("YEAR", _rx(r"(?<![\w.])" + _YEAR_CUE + _YEAR_BODY), group=1,
                  context=_not_money_or_version),
    "all": _Rule("YEAR", _rx(r"(?<![\w.,/:-])(?<!\d[ \t])" + _YEAR_BODY), group=1,
                 context=_not_money_or_version),
}
YEARS = ("off", "near", "all")

# Shapes: found by their form alone. Ordered so that a longer shape claims its digits
# before a shorter one could take the middle of it.
_SHAPES = _DATES + _SPACED_SHAPES + (
    _Rule("IBAN", _rx(r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9]{4}[ ]?){3,7}[A-Z0-9]{1,4}\b")),
    _Rule("IBAN", _rx(r"(?i)\b[a-z]{2}\d{2}(?:[ ]?[a-z0-9]{4}){3,7}(?:[ ]?[a-z0-9]{1,4})?\b"),
          check=_iban_check),
    # A country code never starts with 0.
    _Rule("PHONE", _rx(
        r"(?<![\w+])\+[1-9]\d{0,2}(?:[ .-]?(?:\(0\)|\(\d{1,5}\)|\d{1,6})){1,7}(?!\d)" + _EXT),
        check=_with_extension(_digit_span(8, 15))),
    # An area code in brackets, then two groups, the last of four digits: "(96) 3231-1432",
    # "(81) 99138-7542", "(0161) 496 0000". Eight to twelve digits in all.
    _Rule("PHONE", _rx(
        r"(?<![\w.+(])(?<!\w[/-])\(\d{2,5}\)[ ]?\d{3,5}[ .-]\d{4}(?![ .-]?\d)" + _EXT),
        check=_with_extension(_digit_span(8, 12))),
    # A card is unbroken, grouped with one separator used throughout (so two amounts side
    # by side never join into one), or split by single spaces or dashes.
    _Rule("CARD", _rx(
        r"(?<!\w)(?<!\d[.-])(?:\d{13,19}|\d{4}([ \t]{1,3}|[.-])\d{4}\1\d{4}\1\d{1,4}(?:\1\d{1,3})?"
        r"|\d{4}([ \t]{1,3}|[.-])\d{6}\2\d{5}|(?:\d[ -]?){12,18}\d)(?!\w)(?![.-]\d)"),
          check=_card_check),
    _Rule("NHSNUM", _rx(
        r"(?<![\w.])\d{3}(?:[ \t]{1,2}|[.-])?\d{3}(?:[ \t]{1,2}|[.-])?\d{4}(?![\w])(?![.-]\d)"),
        check=_nhs_check, pack="uk"),
    # UK NI number: two letters, six digits, one letter. D, F, I, Q, U and V never come
    # first or second (QQ is the published example, so it is taken too), which stops an
    # ordinary reference matching by accident. Either case, spaced or dashed.
    _Rule("NINO", _rx(
        r"(?i)\b(?!BG|GB|NK|KN|TN|NT|ZZ)(?:[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]|QQ)"
        r"(?:[ \t-]?\d{2}){3}[ \t-]?[A-D]\b"), pack="uk"),
    # An international number dialled with 00, and a UK mobile written 447... without its +.
    # A 00 number needs a break somewhere, because an unbroken run that starts 00 is far
    # more often a reference with leading zeros than a number someone dialled.
    _Rule("PHONE", _rx(
        r"(?<![\w+.])(?<!\w[/-])00[1-9]\d{0,2}(?:[ .-]?(?:\(0\)|\(\d{1,5}\)|\d{1,6})){1,7}(?!\d)"
        + _EXT), check=_with_extension(_broken_digit_span(10, 17))),
    _Rule("PHONE", _rx(r"(?<!\d)(?:00)?447\d{9}(?!\d)" + _EXT), check=_with_extension(),
          pack="uk"),
    # A UK number written with its country code and no plus: "44 7700 900123".
    _Rule("PHONE", _rx(
        r"(?<![\w+.])(?<!\w[/-])44[ .-]?(?:\(0\)[ .-]?)?[1-9]\d{1,4}(?:[ .-]?\d{2,4}){1,3}(?!\d)"
        + _EXT), check=_with_extension(_broken_digit_span(12, 13)), pack="uk"),
    # A UK number starts 0 then 1 to 9: 00 is the international prefix, never a number.
    _Rule("PHONE", _rx(
        r"(?<![\w+.])(?<!\w[/-])(?:\(0[1-9]\d{1,3}\)|0[1-9]\d{1,3})(?:[ .-]?\d{2,4}){1,3}(?!\d)"
        + _EXT), check=_with_extension(_digit_span(10, 11)), pack="uk"),
    # A North American number: "(212) 555-0134", "212-555-0134", "212.555.0134" or
    # "212 555 0134", with "1" or "+1" before it. A spaced NHS number with a good check was
    # taken just above. With the area code in brackets, or dashes or dots throughout, the
    # shape is a phone whatever its digits, as in the "(555) 015-7148" of test data; with
    # spaces alone the exchange must start 2 to 9.
    _Rule("PHONE", _rx(
        r"(?<![\w.+])(?<!\w[/-])(?<!\d[ .-])(?:\+?1[ .-]?)?(?:\(\d{3}\)[ ]?\d{3}[ .-]\d{4}"
        r"|[2-9]\d{2}([.-])\d{3}\1\d{4}|[2-9]\d{2} [2-9]\d{2} \d{4})(?![ .-]?\d)" + _EXT),
        check=_with_extension(), pack="north-america"),
    # A UK vehicle registration, current style: "WP19 XKD", a code.
    _Rule("CODE", _rx(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}[ \t]?[A-Z]{3}(?![A-Za-z0-9])"), pack="uk"),
    # An Afrikaans or Dutch street with its type joined on: "12 Kerkstraat".
    _Rule("ADDRESS", _rx(
        r"(?<![\w.])\d{1,5}[A-Za-z]?,?[ \t]+[" + _U + r"][a-zà-ÿ]+(?:straat|weg|laan|rylaan|singel|"
        r"plein|steeg|kade|gracht|pad|rinkel)\b"), pack="south-africa"),
    _Rule("POSTCODE", _rx(
        r"(?i)(?<![A-Za-z0-9])(?:GIR[ \t]?0AA|[A-Z]{1,2}\d[A-Z\d]?[^\S\n]{0,2}\d[A-Z]{2})"
        r"(?![A-Za-z0-9])"), check=_postcode_check, pack="uk"),
    _Rule("IP", _rx(
        r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?!\d|\.\d)"), context=_not_a_version),
    _Rule("IP", _rx(r"(?i)(?<![\w:])(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}(?![\w:])")),
    _Rule("IP", _rx(
        r"(?i)(?<![\w:])(?:[0-9a-f]{1,4}:){1,6}:(?:[0-9a-f]{1,4}:){0,5}[0-9a-f]{1,4}(?![\w:])"),
        check=_ipv6_check),
    _Rule("HANDLE", _rx(r"(?<![\w@.])@(?!(?:here|channel|everyone)\b)"
                        r"[A-Za-z0-9_][A-Za-z0-9_.]{0,30}[A-Za-z0-9_]")),
    _Rule("ADDRESS", _rx(
        r"(?<![\w.])\d{1,5}[A-Za-z]?,?[ \t]+(?:" + _STREET_NAME_WORD + r"[ \t]+){1,4}"
        r"(?:" + _STREET_TYPES + r"|" + _STREET_TYPES.upper() + r")\b"), pack="uk"),
    # In lower case, one or two words between the number and the street type, and not
    # a unit or a small word, so "5 minutes down the road" and "2 hours drive" are prose.
    _Rule("ADDRESS", _rx(
        r"(?<![\w.])\d{1,4}[a-z]?,?[ \t]+(?!(?:" + _NOT_A_STREET + r")\b)[a-z][a-z'’-]+"
        r"(?:[ \t]+(?!(?:" + _NOT_A_STREET + r")\b)[a-z][a-z'’-]+)?[ \t]+"
        r"(?:street|road|avenue|lane|close|crescent|terrace|grove|gardens|mews|drive|way)\b"),
        pack="uk"),
) + _CATCH_ALL

#: The detector packs, with what each holds. A pack that is off adds nothing.
PACKS = {
    "general": "emails, links, IP addresses, cards (Luhn), IBANs, international phones, "
               "full dates, long numbers, codes that mix letters and digits, labelled "
               "passwords, keys and PINs, handles, labelled passports, licences, dates of "
               "birth and addresses, JSON fields, numbers read out as words",
    "uk": "NHS numbers (mod 11), National Insurance numbers, sort codes and account "
          "numbers, UK phones, postcodes, house-number addresses, UK vehicle "
          "registrations and driving licences",
    "north-america": "North American phone numbers",
    "south-africa": "South African ID numbers after their label, Afrikaans and Dutch "
                    "street names",
}
#: The packs on when a caller names none.
DEFAULT_PACKS = ("general", "uk", "north-america")

#: Old names for pack sets, kept so older callers work: "clinical" is the default packs,
#: "document" adds south-africa.
PROFILES = {"clinical": DEFAULT_PACKS, "document": DEFAULT_PACKS + ("south-africa",)}

#: Kinds the catch-all and the date rule give: coded out by policy, not by a guess.
POLICY_KINDS = frozenset({"DATE", "CODE", "NUMBER"})


def packs_for(packs=None, profile=None):
    """The packs to run, as a tuple: ``packs`` if given, else the profile's, else the
    default. An unknown pack name is refused."""
    if packs is None:
        if profile is None:
            return DEFAULT_PACKS
        if profile not in PROFILES:
            raise ValueError("unknown hush profile: %r" % (profile,))
        return PROFILES[profile]
    packs = tuple(packs)
    unknown = [p for p in packs if p not in PACKS]
    if unknown:
        raise ValueError("hush: unknown pack %s; the packs are %s"
                         % (", ".join(unknown), ", ".join(PACKS)))
    return packs


def _rules(packs):
    return tuple(rule for rule in _DOCUMENT_LABELLED + _LABELLED + _SHAPES
                 if rule.pack in packs)


def _outside_tokens(text, change, mapping):
    """Apply ``change`` to the stretches between this Mapping's tokens, never to one of
    them, so scrubbing twice changes nothing and no pattern reads the inside of a token.
    Only issued tokens are passed over: anything else shaped like one is text."""
    issued = mapping.issued()
    pieces, cursor = [], 0
    for match in TOKEN.finditer(text):
        if match.group(0) not in issued:
            continue
        pieces.append(change(text[cursor:match.start()]))
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(change(text[cursor:]))
    return "".join(pieces)


def _seal_foreign(text, mapping):
    """A token-shaped string this Mapping did not issue is sealed as a token of its own,
    so whatever it holds never leaves and restore gives it back as it came."""
    issued = mapping.issued()
    return TOKEN.sub(lambda m: m.group(0) if m.group(0) in issued
                     else mapping.token_for(m.group(0), "TOKEN"), text)


def _strip_span(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _apply(rule, text, mapping):
    def change(segment):
        view = _view(segment)
        if rule.ocr:
            view = _ocr_digits(view)
        spans = []
        for match in rule.pattern.finditer(view):
            if rule.groups:
                for group, kind in rule.groups:
                    start, end = _strip_span(view, *match.span(group))
                    if start < end:
                        spans.append((start, end, kind))
                continue
            start, end = match.span(rule.group)
            if rule.check is not None:
                taken = rule.check(match.group(rule.group))
                if taken is None:
                    continue
                start, end = start + taken[0], start + taken[1]
            start, end = _strip_span(view, start, end)
            if start < end and (rule.context is None or rule.context(view, start, end)):
                spans.append((start, end, rule.kind))
        pieces, cursor = [], 0
        for start, end, kind in sorted(spans):
            if start < cursor:
                continue
            pieces.append(segment[cursor:start])
            pieces.append(mapping.token_for(segment[start:end], kind))
            cursor = end
        pieces.append(segment[cursor:])
        return "".join(pieces)
    return _outside_tokens(text, change, mapping)


# --- the roster -------------------------------------------------------------
_WORD = re.compile(r"\w+")
# A double-barrelled continuation: the roster's "Ada Quill" also takes "Ada Quill-Smith".
_BARREL = re.compile(r"-[" + _U + r"][\w'’]*")


@lru_cache(maxsize=8)
def _roster_index(names):
    """Roster entries grouped by their first word, longest first, built once per roster.
    A name of several words matches with any run of spaces or one line break between its
    words, so "Ada  Quill" and "Ada" over "Quill" are the roster's "Ada Quill"."""
    index, odd = {}, []
    for name in sorted({" ".join(n.split()) for n in names if n and n.strip()},
                       key=len, reverse=True):
        first = _WORD.match(name)
        if first is None or not name[-1:].isalnum() and not name[-1:] == "_":
            odd.append(re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.I))
            continue
        words = name.split(" ")
        pattern = re.compile(r"[ \t]*\n?[ \t]*".join(re.escape(w) for w in words) + r"(?!\w)",
                             re.I) if len(words) > 1 else None
        index.setdefault(first.group(0).lower(), []).append((name, pattern))
    return index, tuple(odd)


def _scrub_roster(text, names, mapping):
    """Known names, removed first among the names and unconditionally, whole words only,
    ignoring case: a known name must never depend on a guess going right. A single
    first name is matched like any other entry, so a class's first names go too."""
    if not names:
        return text
    index, odd = _roster_index(tuple(names))

    def change(segment):
        view = _view(segment)
        found, cursor = [], 0
        for word in _WORD.finditer(view):
            if word.start() < cursor:
                continue
            for name, pattern in index.get(word.group(0).lower(), ()):
                if pattern is not None:
                    hit = pattern.match(view, word.start())
                    end = hit.end() if hit else None
                else:
                    end = word.start() + len(name)
                    if (view[word.start():end].lower() != name.lower()
                            or (end < len(view) and re.match(r"\w", view[end]))):
                        end = None
                if end is None:
                    continue
                barrel = _BARREL.match(view, end)
                if barrel:
                    end = barrel.end()
                found.append((word.start(), end))
                cursor = end
                break
        for pattern in odd:
            for match in pattern.finditer(view):
                if not any(s < match.end() and match.start() < e for s, e in found):
                    found.append(match.span())
        # Tokens are allocated left to right, so the first spelling seen is the one a
        # reply gets back, and numbering follows the text.
        tokens = {span: mapping.token_for(segment[span[0]:span[1]], "PERSON")
                  for span in sorted(found)}
        out = segment
        for start, end in sorted(found, reverse=True):
            out = out[:start] + tokens[(start, end)] + out[end:]
        return out
    return _outside_tokens(text, change, mapping)


# --- fields in structured text ------------------------------------------------
# A JSON record names its fields, so a value under "first_name" is a name whatever it
# looks like. An address split into a user field and a domain field is still an
# address, so the domain goes when a user field sits beside it.
_FIELD = re.compile(
    r'"(?P<key>[A-Za-z_][A-Za-z0-9_ -]{0,40})"\s*:\s*"(?P<value>(?:[^"\\\n]|\\.){1,200})"')
_PERSON_KEYS = {"name", "full_name", "fullname", "first_name", "firstname", "given_name",
                "last_name", "lastname", "surname", "family_name", "forename",
                "middle_name", "display_name", "patient", "patient_name", "contact_name",
                "sender_name", "recipient_name", "from_name", "to_name"}
_EMAIL_KEYS = {"email", "e_mail", "email_address", "mail"}
_USER_KEYS = {"user", "username", "user_name", "login", "local_part", "mailbox"}
_DOMAIN_KEYS = {"domain", "email_domain", "mail_domain"}
_FIELD_KINDS = {
    **{key: "PERSON" for key in _PERSON_KEYS},
    **{key: "EMAIL" for key in _EMAIL_KEYS},
    **{key: "PHONE" for key in ("phone", "phone_number", "mobile", "mobile_number", "tel",
                                "telephone")},
    **{key: "ADDRESS" for key in ("address", "street", "street_address", "address_line_1",
                                  "address1", "home_address")},
    **{key: "POSTCODE" for key in ("postcode", "post_code", "postal_code", "zip",
                                   "zip_code")},
    **{key: "DOB" for key in ("dob", "date_of_birth", "birth_date", "birthday")},
    **{key: "NHSNUM" for key in ("nhs_number", "nhs_no")},
    **{key: "NINO" for key in ("ni_number", "nino", "national_insurance_number")},
    **{key: "SECRET" for key in ("password", "api_key", "apikey", "secret", "token",
                                 "access_token", "client_secret")},
}


def _field_key(raw):
    return re.sub(r"[\s-]+", "_", raw.strip().lower())


def _field_kind(key, split_address):
    if key in _USER_KEYS:
        return "EMAIL" if split_address else "HANDLE"
    if key in _DOMAIN_KEYS:
        return "EMAIL" if split_address else None
    kind = _FIELD_KINDS.get(key)
    if kind is None and re.search(r"(?:^|_)(?:name|surname|forename)(?:_|$)", key):
        return "PERSON"
    return kind


def _scrub_fields(text, mapping):
    keys = {_field_key(m.group("key")) for m in _FIELD.finditer(text)}
    split_address = bool(keys & _USER_KEYS) and bool(keys & _DOMAIN_KEYS)

    def change(segment):
        def repl(match):
            kind = _field_kind(_field_key(match.group("key")), split_address)
            if kind is None:
                return match.group(0)
            start, end = _strip_span(segment, *match.span("value"))
            if start >= end:
                return match.group(0)
            token = mapping.token_for(segment[start:end], kind)
            return segment[match.start():start] + token + segment[end:match.end()]
        return _FIELD.sub(repl, segment)
    return _outside_tokens(text, change, mapping)


# --- the capitalised-word guess ------------------------------------------------
_TITLE_NAMES = r"(?:Dr|Mr|Mrs|Ms|Mx|Miss|Prof|Professor|Sir|Dame|DR|MR|MRS|MS|MX|MISS|PROF|SIR|DAME)"
# A title, with any bare initials after it ("Dr A Quill"), when a capitalised word follows.
_TITLE_WORD = (_TITLE_NAMES + r"\.?(?:[ \t]+[" + _U + r"]\.?(?=[ \t]+[" + _U + r"])){0,2}"
               r"(?=[ \t]+[" + _U + r"])")
_NAME_WORD = (r"[" + _U + r"][" + _L + r"]+(?:(?:['’-]?[" + _U + r"]|-)[" + _L + r"]+)*"
              r"|[" + _U + r"]['’][" + _U + r"][" + _L + r"]+(?:-[" + _U + r"]?[" + _L + r"]+)*")
# A surname in capitals, the NHS letter convention. Only a name in the right company.
_CAPS_WORD = (r"[" + _U + r"](?:['’][" + _U + r"])?[" + _U + r"]+(?:-[" + _U + r"]{2,})*")
# An initial counts only before another capitalised word, so "A. Quill" is a run and
# the full stop after "Workshop A." stays a full stop.
_INITIAL = r"[" + _U + r"]\.(?=[ \t]+[" + _U + r"])"
_PART = (r"(?:" + _TITLE_WORD + r"|" + _NAME_WORD + r"|" + _CAPS_WORD + r"|" + _INITIAL + r")")
_PART_RE = re.compile(_PART)
# A run of capitalised words: the shape of a person, a hospital or a street. A run may
# end before a possessive ("Dr Quill's"), never inside a word ("O'Brien").
_PROPER = re.compile(r"(?<![\w'’-])(" + _PART + r"(?:[ \t]+" + _PART + r"){0,3})"
                     r"(?!\w)(?!['’](?![sS]\b)\w)")

# What before a run says a name follows, so capitals there are a surname.
_NAME_LABEL_BEFORE = re.compile(
    r"(?i)(?:\b(?:(?:full|first|last|given|family|middle|maiden|patient(?:'s)?|account|"
    r"card|policy)[ \t]+)?(?:names?|surname|forename)\b[ \t]*[:|-]?|"
    r"\bpatient(?:'s)?\b[ \t]*[:|-]?|\b(?:dear|attn|fao)\b[ \t]*:?|"
    r"\b(?:re|to|from|cc|payee|payer|beneficiary|holder|cardholder|policyholder|applicant|"
    r"claimant|insured|member|customer|client|recipient|sender|signed|contact|kin|carer|"
    r"parent|guardian|child|spouse|partner|referrer|consultant|gp|doctor|clinician|"
    r"seen[ \t]+by)[ \t]*:)[ \t]*(?:\n[ \t]*)?\Z")
_PERSON_BEFORE = re.compile(r"(?i)\b(?:by|with|from|to|for|and|cc)[ \t]+\Z")
# "Name: QUILL, Ada": the surname first, in capitals, then a comma and the forename.
_SURNAME_FIRST = re.compile(
    r"(?i:\b(?:(?:full|patient(?:'s)?)[ \t]+)?(?:names?|surname)\b|\bpatient\b|\bre\b)"
    r"[ \t]*[:|-]?[ \t]*(?:\n[ \t]*)?(?P<n>" + _CAPS_WORD + r"(?:[ \t]+" + _CAPS_WORD + r")?,"
    r"[ \t]*(?:" + _TITLE_NAMES + r"\.?[ \t]+)?(?:" + _NAME_WORD + r"|" + _CAPS_WORD + r")"
    r"(?:[ \t]+(?:" + _NAME_WORD + r"|[" + _U + r"]\.?))?)(?![\w'’])")

# Words that mark the run before or after them as a place of care, not a person.
_PLACE_WORDS = {"hospital", "clinic", "centre", "center", "ward", "unit",
                "surgery", "practice", "trust", "institute", "hospice"}
# Titles that mark the run after them as a person, and which of them a clinician.
_CLINICAL_TITLES = {"dr", "doctor", "prof", "professor", "nurse", "sister", "consultant"}
_SOCIAL_TITLES = {"mr", "mrs", "ms", "mx", "miss", "sir", "dame"}
_TITLES = _CLINICAL_TITLES | _SOCIAL_TITLES
# Honorifics, after which any word is a surname ("Dr May"). A role word is not one:
# "Consultant Rheumatologist" is a job.
_HONORIFICS = {"dr", "mr", "mrs", "ms", "mx", "miss", "prof", "professor", "sir", "dame"}


def _protected(word):
    bare = word.strip(".,;:!?()")
    return bare.lower() in keep_words() or bool(_CLINICAL_SUFFIX.match(bare))


def _bare(word):
    return word.split()[0].rstrip(".").lower() if word.split() else ""


def _is_title(word):
    return _bare(word) in _TITLES


def _is_caps(word):
    letters = re.sub(r"[^\w]", "", word)
    return len(letters) >= 2 and letters.isupper() and not _is_title(word)


def _classify_proper(text, start, end):
    """PERSON, CLINICIAN, PLACE or None for one capitalised run, judged by its
    neighbours."""
    run = text[start:end]
    words = run.split()
    bare = [w.rstrip(".").lower() for w in words]
    if all(w in _TITLES or len(w) == 1 for w in bare):
        return None
    before = text[max(0, start - 24):start].lower()
    after = text[end:end + 24].lower()
    prior = re.findall(r"[a-z&.']+", before)
    title = bare[0] if bare[0] in _TITLES else (
        prior[-1].rstrip(".") if prior and prior[-1].rstrip(".") in _TITLES else None)
    if title:
        return "CLINICIAN" if title in _CLINICAL_TITLES else "PERSON"
    if any(w in _PLACE_WORDS for w in bare):
        return "PLACE"
    if any(after.strip().startswith(w) for w in _PLACE_WORDS):
        return "PLACE"
    # A single capitalised word mid-sentence is usually a name; at the start of a
    # sentence it is usually just a sentence. Only take multi-word runs there.
    at_sentence_start = not before.strip() or before.rstrip()[-1:] in ".!?\n"
    if len(words) == 1 and at_sentence_start:
        return None
    # "Room 214", "Ward 22", "Level 2", "Council Tax Bill 2026/27": a capitalised run
    # with a number straight after it on the same line names a place, a thing or a
    # heading, not a person, and so does a run before a word like "Room" with a number
    # ("Seminar Room 3").
    if re.match(r"[ \t]+\(?\d", text[end:end + 4]):
        return None
    # A word alone in a table cell is a heading ("| Week | Sessions |"), and a single
    # word after "in" or "near" is a place ("in Exeter"), unless it owns something.
    if len(words) == 1 and re.search(r"\|[ \t*]*\Z", text[max(0, start - 4):start]) and \
            re.match(r"[ \t*]*\|", text[end:end + 4]):
        return None
    if re.search(r"(?i)\b(?:in|near|around|across|throughout)[ \t]+\Z",
                 text[max(0, start - 12):start]) and not re.match(r"['’]s\b", text[end:end + 2]):
        return None
    if prior and prior[-1] in _DETERMINERS:
        return None
    # A quantity's noun ("4 Pints"), and an item at the start of a line or a table cell
    # with a lower-case word after it ("Oat milk"), are not people.
    if re.search(r"\d[ \t]+\Z", text[max(0, start - 8):start]):
        return None
    if re.search(r"(?:\A|\n|\|)[ \t*]*\Z", text[max(0, start - 8):start]) and \
            re.match(r"[ \t]+[a-z]", text[end:end + 3]):
        return None
    following = re.match(r"[ \t]+([A-Za-z]+)[ \t]+\d", text[end:end + 24])
    if following and following.group(1).lower() in _FORM_WORDS:
        return None
    return "PERSON"


def _sub_runs(text, start, end):
    """Split one capitalised run into the runs that may be names, as lists of parts.

    It splits at protected words, which stay as they are, at form labels and greetings,
    and before a title. "Started Pythagoras" leaves "Started" to be judged alone, "Theresa
    May" keeps the month, "Account No" is no one, and "Ask Dr May" leaves "Ask" alone.
    Straight after a title any of those words is a surname ("Dr May", "Dr Best"), and a
    name-like month before a surname is a first name ("April Moss")."""
    parts = list(_PART_RE.finditer(text, start, end))
    runs, current = [], []
    for i, part in enumerate(parts):
        word = part.group(0)
        low = word.rstrip(".").lower()
        after_title = i > 0 and _bare(parts[i - 1].group(0)) in _HONORIFICS
        following = parts[i + 1].group(0) if i + 1 < len(parts) else ""
        if _is_title(word):
            if current:
                runs.append(current)
            current = [part]
            continue
        stop = low in _FORM_WORDS or low in _GREETINGS or (
            _protected(word) and not (low in _NAME_LIKE_KEEP and re.fullmatch(_NAME_WORD, following)
                                      and not _protected(following)
                                      and following.lower() not in _FORM_WORDS))
        if stop and not after_title:
            if current:
                runs.append(current)
            current = []
            continue
        current.append(part)
    if current:
        runs.append(current)
    return runs


def _allow_capitals(text, run):
    """The parts of one run that may stand as a name. A word in capitals counts only
    in a name's company: after a title, after a name label ("Patient:", "Name:",
    "Re:"), or after a forename when a word like "by" or "with" comes before. Anywhere
    else the capitals are an acronym or emphasis, and the run is split around them."""
    if not any(_is_caps(part.group(0)) for part in run):
        return [run]
    before = text[max(0, run[0].start() - 48):run[0].start()]
    if _is_title(run[0].group(0)) or _NAME_LABEL_BEFORE.search(before):
        return [run]
    forename_first = not _is_caps(run[0].group(0))
    if forename_first and _PERSON_BEFORE.search(before):
        return [run]
    kept, current = [], []
    for part in run:
        if _is_caps(part.group(0)):
            if current:
                kept.append(current)
            current = []
        else:
            current.append(part)
    if current:
        kept.append(current)
    return kept


def _scrub_proper(text, mapping, guess_filter=None):
    text = _apply(_Rule("PERSON", _SURNAME_FIRST, group="n"), text, mapping)
    view = _view(text)
    pieces = []
    for match in _PROPER.finditer(view):
        for run in _sub_runs(view, match.start(1), match.end(1)):
            for parts in _allow_capitals(view, run):
                start, end = parts[0].start(), parts[-1].end()
                kind = _classify_proper(view, start, end)
                if kind and (guess_filter is None or guess_filter(view, start, end)):
                    pieces.append((start, end, mapping.token_for(text[start:end], kind)))
    out = text
    for start, end, token in reversed(pieces):
        out = out[:start] + token + out[end:]
    return out


# --- the three verbs ------------------------------------------------------------
def scrub(text, mapping=None, *, date_shift=0, extra_names=(), heuristic_names=True,
          profile=None, packs=None, keep=(), people=None, guess_filter=None, students=None,
          years="off"):
    """Return ``(scrubbed_text, mapping)``.

    ``packs`` names the detector packs to run (``PACKS``; default ``DEFAULT_PACKS``).
    ``profile`` is the older way to say the same ("clinical", "document").

    ``keep`` is words the caller's text uses that are never a name (product names, a
    sector's vocabulary), added to ``KEEP`` for this call.

    ``extra_names`` is the roster the caller already knows: customers, staff, the
    correspondents in the mail. Roster entries are matched
    as whole words, ignoring case, after email addresses and links and before every
    other rule.

    ``heuristic_names`` (default True) controls the capitalised-word guess, the last
    pass, which is the piece that turns "Career" into a person when no real name is
    there. Pass False only when the caller supplies a real roster; every pattern still
    runs. The trade: text that survives intact, at the cost of any name that is not on
    the roster and not otherwise flagged going through.

    ``people`` is an optional callable ``(text, mapping) -> text``, run after email
    addresses and links and before the roster: a detector that knows more than this
    module does (``hush.people.People.detector``). It must allocate its tokens from
    the same Mapping, so every later rule leaves them alone. ``students`` is its older
    name.

    ``guess_filter`` is an optional callable ``(view, start, end) -> bool`` that the
    capitalised-name guess asks before it takes ``view[start:end]``; False leaves the
    words alone (``hush.people.keep_guess``).

    ``years`` is "off" (the default), "near" or "all": whether a year on its own, 1900
    to 2099, is a YEAR token, after a word that dates it or wherever it stands.

    ``date_shift`` is retired and refused when not zero: every full date is a DATE token,
    which restore puts back exactly, where a shifted date a model rewrites would come back
    wrong.
    """
    packs = packs_for(packs, profile)
    rules = _rules(packs)
    general = "general" in packs
    if date_shift:
        raise ValueError("hush: date_shift is retired; full dates are coded out as DATE tokens")
    if mapping is None:
        mapping = Mapping()
    active = _ACTIVE_KEEP.set(
        frozenset(KEEP) | {fold(w) for w in keep} | {w.lower() for w in keep})
    try:
        out = _seal_foreign(text, mapping)
        if general:
            out = _scrub_columns(out, mapping)
            for rule in _FIRST:
                out = _apply(rule, out, mapping)
        out = _scrub_addresses(out, mapping, packs)
        detector = people if people is not None else students
        if detector is not None:
            out = detector(out, mapping)
        out = _scrub_roster(out, tuple(extra_names), mapping)
        if general:
            out = _scrub_fields(out, mapping)
            out = _scrub_spoken(out, mapping)
        for rule in rules:
            out = _apply(rule, out, mapping)
        if years in _YEARS:
            out = _apply(_YEARS[years], out, mapping)
        elif years != "off":
            raise ValueError("hush: years must be one of %s" % ", ".join(YEARS))
        if general:
            out = _scrub_numbers(out, mapping)
        if heuristic_names:
            out = _scrub_proper(out, mapping, guess_filter)
    finally:
        _ACTIVE_KEEP.reset(active)
    return out, mapping


@dataclass(frozen=True)
class Restored:
    """A restored reply and what restoring it found. ``restore_misses`` counts every
    token-shaped thing that was not an exact token of this Mapping."""
    text: str
    restored: int
    restore_misses: int
    misses_by_reason: dict


def restore_report(text, mapping):
    """Put the real words back into a reply, and count what could not be put back.

    Only an exact token this Mapping issued is replaced. A well-formed token from another
    namespace, one with a check this Mapping did not compute, or one it never issued is
    left as it is and counted. So is anything that looks like part of a token (a changed
    case, a lost bracket, a fullwidth look-alike). Dates are not shifted back.
    """
    issued = mapping.by_token
    reasons = {}
    restored = 0

    def miss(reason):
        reasons[reason] = reasons.get(reason, 0) + 1

    def repl(match):
        nonlocal restored
        token = match.group(0)
        if match.group("namespace") != mapping.namespace:
            miss("foreign_namespace")
            return token
        expected = mapping.check_for(match.group("kind"), int(match.group("index")))
        if not hmac.compare_digest(expected, match.group("check")):
            miss("bad_check")
            return token
        real = issued.get(token)
        if real is None:
            miss("unknown_token")
            return token
        restored += 1
        return real

    out = TOKEN.sub(repl, text)
    rest = unicodedata.normalize("NFKC", TOKEN.sub(" ", text))
    spans = sorted(m.span() for pattern in (_TOKEN_BODY_LIKE, _TOKEN_OPEN_PREFIX_LIKE)
                   for m in pattern.finditer(rest))
    last_end = -1
    for start, end in spans:
        if start >= last_end:
            miss("lookalike")
        last_end = max(last_end, end)
    return Restored(out, restored, sum(reasons.values()), reasons)


def restore(text, mapping):
    """Put the real words back into a reply. See :func:`restore_report` for the rules
    and for the count of what could not be put back."""
    return restore_report(text, mapping).text


def audit(text, mapping, *, profile=None, packs=None, keep=()):
    """What a person needs to see before they press send: what is going out, and what
    was taken out of it. Counts by class, never the values.

    The second pass runs scrub again on a copy of the mapping, patterns first and then
    the capitalised-word guess, and reports the kinds it would still take. It can only
    report what those rules see; this is not a claim that every identifier is found.
    """
    packs = packs_for(packs, profile)
    counts = {}
    for token in mapping.by_real.values():
        kind = kind_of(token)
        counts[kind] = counts.get(kind, 0) + 1
    probe = mapping.copy()
    probe.day_offset = 0
    patterned, probe = scrub(text, probe, packs=packs, keep=keep, heuristic_names=False)
    before = _kind_counts(text)
    leftovers = [kind for kind, n in _kind_counts(patterned).items() if n > before.get(kind, 0)]
    proper, _ = scrub(patterned, probe, packs=packs, keep=keep, heuristic_names=True)
    if proper != patterned:
        leftovers.append("PROPER")
    return {"removed": counts,
            "date_shift_days": mapping.day_offset,
            "still_present": leftovers,
            "clean": not leftovers}


def _kind_counts(text):
    counts = {}
    for match in TOKEN.finditer(text):
        counts[match.group("kind")] = counts.get(match.group("kind"), 0) + 1
    return counts
