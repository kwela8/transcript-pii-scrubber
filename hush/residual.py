"""The second check: an independent detector run on hush's output before anything leaves.

Its patterns were written apart from hush's, so a shape hush misses gets a second,
differently built look. Any finding means the text must not leave. It reports kinds and
counts, never the matched text, so a refusal can be logged without carrying what it
refused.

Each pattern needs the shape of the thing it names, so that ordinary text is not refused
for a passing resemblance: PHONE needs a phone number's form, URL needs something after
its scheme, ACCOUNT_ID needs its cue and then an account number, SECRET needs a ":" or
"=" after its cue, POSTAL_ADDRESS needs capitalised street words, UK_POSTCODE needs
capitals, PERSON keeps a title and its name on one line. An unlabelled
card or NHS number has a check of its own (Luhn, mod 11).

Only tokens the current Mapping issued are blanked before the scan; anything else shaped
like a token is read as text, so a forged token cannot carry a number past it. The text
is NFKC-normalised first, so a fullwidth digit reads as a digit.

Standard library only.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from hush import core as hush

VERSION = "hush-residual-v3"


def _digit_count(text):
    return sum(char.isdigit() for char in text)


def _luhn(digits):
    total, alt = 0, False
    for char in reversed(digits):
        number = int(char)
        if alt:
            number = number * 2 - 9 if number > 4 else number * 2
        total += number
        alt = not alt
    return total % 10 == 0


def _mod11(digits):
    total = sum(int(d) * w for d, w in zip(digits[:9], range(10, 1, -1)))
    check = (11 - total % 11) % 11
    return check != 10 and check == int(digits[9])


def _digits_at_least(n):
    return lambda match: _digit_count(match.group(0)) >= n


def _digits_between(low, high):
    return lambda match: low <= _digit_count(match.group(0)) <= high


def _card(match):
    digits = re.sub(r"\D", "", match.group(0))
    return 13 <= len(digits) <= 19 and _luhn(digits)


def _nhs(match):
    digits = re.sub(r"\D", "", match.group(0))
    return len(digits) == 10 and _mod11(digits)


def _dialled(match):
    """A + number with eight digits, or a 00 number with eight digits and a break in it."""
    text = match.group(0)
    return _digit_count(text) >= 8 and (text.startswith("+") or bool(re.search(r"[\s.()-]", text)))


# A software version is not an address: "software 4.12.0.7", "v1.2.3.4", "iOS 17.4.1.2".
_VERSION_BEFORE = re.compile(
    r"(?i)(?:\bv|\bver\.?|\bversion|\bbuild|\brelease|\bfirmware|\bsoftware|\bupdate|"
    r"\bpatch|\bios|\bandroid|\bchrome|\bfirefox|\bwindows|\bmacos|\bapp|\bdriver)[ \t:]*v?\Z")


def _not_a_version(match):
    return not _VERSION_BEFORE.search(match.string[max(0, match.start() - 20):match.start()])


# A secret's position: a key or label ending in password, pass, secret, token, key, pin,
# cvv, cvc, code or kode. Any value left there after hush is refused: secrets
# never travel. A value is a letter, digit or symbol, not a full stop.
# A bare "pass" is a key only with "=" or a quoted value, as in hush.
_MORE_LABELS = (r"memorable[ \t]+(?:word|information|answer|name|date|place)|"
                r"mot[ \t]+de[ \t]+passe|wachtwoord|passwort|kennwort|contrase[ñn]a|senha|"
                r"key[ \t]*safe|lock[ \t]*box|pin[ \t-]*(?:nommer|nummer|number|no\.?|code)|"
                r"pwd|passphrase|wagwoord")
_HIDDEN_KEY = (r"(?:" + _MORE_LABELS + r"|(?:[A-Za-z0-9]+[_.-])*(?:password|passwd|passcode|"
               r"passphrase|pwd|secret|token|key|apikey|passkey|pin|cvv2?|cvc2?|code|kode|"
               r"wagwoord)|(?:[A-Za-z0-9]+[_.-])+pass|pass(?=[\"']?[ \t]*(?:=|:[ \t]*[\"'])))")
_HIDDEN_LABEL = (r"(?:" + _MORE_LABELS + r"|password|passwd|passcode|"
                 r"pin(?:[ \t]*(?:code|number|no\.?))?|cvv2?|cvc2?|(?:[A-Za-z-]+[ \t]+)?code|kode)")
_OPENS_WITH = r"(?:[ \t]+(?:opens|open|unlocks|unlock|works|goes)[ \t]+with)?"
_VALUE_CHAR = r"[^\s\"'<>.,;:)\]}\ue000]"
_PROSE_WORDS = {
    "the", "a", "an", "to", "for", "of", "and", "or", "in", "on", "at", "by", "with", "not",
    "now", "here", "there", "below", "above", "attached", "enclosed", "incorrect", "wrong",
    "invalid", "valid", "expired", "required", "needed", "changed", "reset", "sent", "same",
    "protected", "strong", "weak", "too", "very", "still", "also", "being", "ready", "set",
    "it", "this", "that", "your", "my", "our", "their", "his", "her", "empty", "blank",
    "missing", "unknown", "different", "correct", "ok", "fine", "simple", "easy", "hard",
    "long", "short", "secure", "safe", "private", "confidential", "shown", "given",
    "printed", "written", "case", "ek", "die", "nie", "jou",
}


def _not_prose(match):
    return match.group("w").strip("\"'.,;:!?").lower() not in _PROSE_WORDS


def _account(match):
    value = match.group("v")
    return bool(re.match(r"[A-Z]{2}\d{2}", value)) or _digit_count(value) >= 6


_NOT_IN_A_NUMBER = r"(?<![\w+.,])"
# A cue may sit a line above its number, and a few words before it.
# Crossing a line only when the cue ends its line, so "Account settings" never reads the
# next line's numbers as an account.
_NEAR = r"(?:[^\n\d]{0,24}?|[ \t]*[:#|.-]?[ \t]*\n[ \t]*)"
# Between digit groups: up to three spaces, or a dot, dash or slash.
_GS = r"(?:[ \t]{1,3}|[ \t]*[./-][ \t]*)"
_STREET = (r"(?:Street|Road|Avenue|Lane|Drive|Close|Court|Terrace|Crescent|Mews|"
           r"STREET|ROAD|AVENUE|LANE|DRIVE|CLOSE|COURT|TERRACE|CRESCENT|MEWS)")

#: (kind, pattern, check). A match counts only when its check, if any, says so.
_CHECKS = (
    ("EMAIL", re.compile(r"(?i)[^\s@<>]{1,64}\s*@\s*[^\s@<>]{1,255}\.[A-Z]{2,}"), None),
    ("PHONE", re.compile(
        _NOT_IN_A_NUMBER + r"(?:\+|00)[1-9]\d{0,2}(?:[\s.-]?(?:\(0\)|\(\d{1,5}\)|\d{1,6})){1,7}"
        r"(?!\d)"), _dialled),
    ("PHONE", re.compile(
        _NOT_IN_A_NUMBER + r"(?:\(0[1-9]\d{1,4}\)|0[1-9]\d{1,4})[\s.-]?\d{3,4}[\s.-]?\d{3,4}"
        r"(?!\d)"),
     _digits_between(10, 11)),
    ("PHONE", re.compile(r"(?<!\d)(?:00)?447\d{9}(?!\d)"), None),
    ("PHONE", re.compile(
        _NOT_IN_A_NUMBER + r"44[\s.-]?(?:\(0\)[\s.-]?)?[1-9]\d{1,4}(?:[\s.-]?\d{2,4}){1,3}(?!\d)"),
     lambda match: 12 <= _digit_count(match.group(0)) <= 13
     and bool(re.search(r"[\s.()-]", match.group(0)))),
    ("PHONE", re.compile(
        r"(?<![\w.])(?<!\d[ .-])(?:\([2-9]\d{2}\)[ ]?|[2-9]\d{2}[ .-])[2-9]\d{2}[ .-]\d{4}"
        r"(?![ .-]?\d)"), None),
    ("URL", re.compile(
        r"(?i)(?:https?\s*:\s*/\s*/|www\s*\.)[^\s.,;:!?'\"()\[\]{}<>]\S*"), None),
    ("IP_ADDRESS", re.compile(r"(?<!\d)\d{1,3}(?:\s*\.\s*\d{1,3}){3}(?!\d)"), _not_a_version),
    ("UK_POSTCODE", re.compile(
        r"(?<![A-Za-z0-9])(?:GIR ?0AA|[A-Z]{1,2}\d[A-Z\d]?[^\S\n]{0,2}\d[A-Z]{2})"
        r"(?![A-Za-z0-9])"), None),
    ("UK_POSTCODE", re.compile(
        r"(?<![A-Za-z0-9])[a-z]{1,2}\d[a-z\d]? \d[a-z]{2}(?![A-Za-z0-9])"), None),
    ("NHS_NUMBER", re.compile(r"(?i)\bNHS\b[^\n]{0,16}\d{3}\D?\d{3}\D?\d{4}"), None),
    ("NHS_NUMBER", re.compile(
        r"(?<!\d)(?<!\d[ .-])\d{3}" + _GS + r"?\d{3}" + _GS + r"?\d{4}(?!" + _GS + r"?\d)"), _nhs),
    ("UK_NINO", re.compile(
        r"(?i)(?<![A-Z0-9])[ABCEGHJKLMNPRSTWXYZ]{2}\D?\d{2}\D?\d{2}\D?\d{2}\D?[A-D](?![A-Z0-9])"),
     None),
    ("PAYMENT_CARD", re.compile(
        r"(?i)\b(?:card|visa|mastercard)\b[^\n]{0,12}(?:\d[ -]?){13,19}"), None),
    ("PAYMENT_CARD", re.compile(
        r"(?<!\d)(?<!\d[ .-])(?:\d(?:\s{1,3}|[.-])?){12,18}\d(?![ .-]?\d)"), _card),
    ("ACCOUNT_ID", re.compile(
        r"(?i)\b(?:IBAN|account|acct|acc|a/c|sort[ -]?code|s/c)\b\.?(?:[ \t]*(?:no\.?|number|num|#))?"
        + _NEAR + r"(?P<v>(?i:[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?)"
        r"|\d(?:" + _GS + r"?\d){5,17})(?![A-Za-z0-9])"), _account),
    # A sort code beside an eight-digit number, with no cue.
    ("ACCOUNT_ID", re.compile(r"(?<![\d.-])\d{2}-\d{2}-\d{2}[ \t,/|;]{1,4}\d{8}(?!\d)"), None),
    ("HANDLE", re.compile(r"(?<!\w)@(?!(?:here|channel|everyone)\b)[A-Za-z0-9_.-]{2,32}"),
     None),
    ("SECRET", re.compile(r"(?im)^[ \t]*(?:[-*][ \t]+)?[\"']?" + _HIDDEN_KEY
                          + r"[\"']?[ \t]*[:=][ \t]*[\"']?" + _VALUE_CHAR), None),
    ("SECRET", re.compile(r"(?i)\"" + _HIDDEN_KEY + r"\"[ \t]*:[ \t]*\"?" + _VALUE_CHAR), None),
    ("SECRET", re.compile(r"(?i)(?<![\w-])" + _HIDDEN_KEY + r"[ \t]*[:=][ \t]*[\"']?" + _VALUE_CHAR),
     None),
    ("SECRET", re.compile(r"(?i)(?<![\w-])" + _HIDDEN_LABEL + r"[ \t]+(?:is|was)[ \t]+[\"']?"
                          r"(?P<w>" + _VALUE_CHAR + r"[^\s\"'<>]*)"), _not_prose),
    ("SECRET", re.compile(r"(?i)(?<![\w-])" + _HIDDEN_LABEL + _OPENS_WITH
                          + r"[ \t]+(?=\S*[\d#*!$%&@?])" + _VALUE_CHAR), None),
    # A label alone on its line, a value on the next line that is not a label itself.
    ("SECRET", re.compile(r"(?im)^[ \t]*(?:[-*#>][ \t]*)*(?:" + _HIDDEN_KEY + r"|" + _HIDDEN_LABEL
                          + r")[ \t]*[:=#-]?[ \t]*\n[ \t]*(?![^\n]{0,40}:[ \t])" + _VALUE_CHAR), None),
    ("SECRET", re.compile(
        r"(?i)\b(?:api.?key|secret|password|passwd|bearer)\b[ \t]*[:=][ \t]*[\"']?"
        r"[A-Za-z0-9_./+\-=]{8,}"), None),
    ("SECRET", re.compile(
        r"(?i)\b(?:password|passwd|passcode)\b[ \t]+is[ \t]+[\"']?"
        r"(?=[A-Za-z0-9_./+\-=]*[\d_./+\-=])[A-Za-z0-9_./+\-=]{8,}"), None),
    ("SECRET", re.compile(r"(?i)\bbearer[ \t]+[A-Za-z0-9_./+\-=~]{16,}"), None),
    ("POSTAL_ADDRESS", re.compile(
        r"\b\d{1,5}[A-Za-z]?,?[ \t]+[A-ZÀ-Þ][A-Za-zÀ-ÿ'’-]*[ \t]+"
        r"(?:(?:[A-ZÀ-Þ][A-Za-zÀ-ÿ'’-]*|of|on|upon|the|de|le|la)[ \t]+){0,4}" + _STREET + r"\b"),
     None),
    ("PERSON", re.compile(
        r"(?u)\b(?:Dr|Mr|Mrs|Ms|Mx|Professor)\.?[ \t]+[A-Z][^\W\d_'-]+(?:[ \t]+[A-Z][^\W\d_'-]+){0,2}"),
     None),
    ("QUASI_IDENTIFIER", re.compile(
        r"(?i)\b(?:born|birthday|appointment|meeting)\b[^\n]{0,10}\d{1,2}[/-]\d{1,2}[/-](?:19|20)\d{2}"),
     None),
)


@dataclass(frozen=True)
class Finding:
    """One finding: its kind and where it sits in the scanned text. Never the text."""
    kind: str
    start: int
    end: int


_DASHES = {code: "-" for code in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212,
                                  0xFE58, 0xFE63, 0xFF0D)}


#: What an issued token reads as: one private-use character, neither a space nor a word
#: character, so words either side stay apart and a secret's position that holds a token
#: reads as coded, not as empty with the next word as its value.
TOKEN_MARK = "\ue000"


def scanned(text, mapping=None):
    """The text the checks read: every token ``mapping`` issued one TOKEN_MARK, then NFKC,
    then every dash a "-". A token-shaped string the mapping did not issue stays text."""
    issued = mapping.issued() if mapping is not None else set()
    blanked = hush.TOKEN.sub(lambda m: TOKEN_MARK if m.group(0) in issued else m.group(0), text)
    return unicodedata.normalize("NFKC", blanked).translate(_DASHES)


def findings(text, mapping=None):
    """Every finding in ``text``, overlaps merged (the longest span wins), left to right.
    ``mapping`` is the Mapping that scrubbed the text: only its tokens are passed over.
    A cell under a secret column's header that holds anything but a token is a finding."""
    view = scanned(text, mapping)
    found = [Finding(kind, *match.span())
             for kind, pattern, check in _CHECKS for match in pattern.finditer(view)
             if check is None or check(match)]
    found += [Finding("SECRET", start, end) for start, end in hush.secret_column_spans(view)
              if view[start:end].strip(" \t" + TOKEN_MARK)]
    kept = []
    for item in sorted(found, key=lambda f: (-(f.end - f.start), f.start, f.kind)):
        if any(item.start < old.end and old.start < item.end for old in kept):
            continue
        kept.append(item)
    return sorted(kept, key=lambda f: (f.start, f.end, f.kind))


def check(text, mapping=None):
    """Counts by kind, and whether the text is clean. Any finding means it must not leave.
    Pass the Mapping that scrubbed the text, so its tokens are read as tokens."""
    counts = {}
    for item in findings(text, mapping):
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return {"clean": not counts, "found": counts, "version": VERSION}
