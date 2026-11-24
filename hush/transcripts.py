"""Speaker labels in call, meeting and chat transcripts, and role cues near a name.

A transcript names its speaker at the start of each turn, in many shapes:

    Agent: ...                    Speaker 1: ...             SPEAKER_01: ...
    [00:01:02] Priya: ...         00:01:02 Customer: ...     (10:02) Priya Shah: ...
    PRIYA (10:02): ...            Priya Shah [00:01:02]: ...  <v Priya Shah>... (WebVTT)

:func:`speakers` finds them. A label that names a role ("Agent", "Customer", "Speaker 2",
"Interviewer") is generic and is left as it is. A label that is a person's name is handled
as the config says (``[transcript] speakers``):

- ``text`` (the default): the label is text like any other, and the name rules apply.
- ``keep``: the speaker is kept, in the label and wherever the transcript names them.
- ``relabel``: the speaker becomes a known person with the role the config gives that
  label (``[transcript] roles``), or "speaker", so the label and every mention of them
  become one placeholder ("[agent 1]:", "[speaker 2]:").

:func:`cue_roles` reads the words around each name that was removed and gives the name a
role when a cue word the config names sits within a few words of it in the same sentence
("my son [person 1]" becomes "my son [child 1]"). Every name a cue changed is flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from hush import core
from hush.core import fold

_TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?"
_LABEL = re.compile(
    r"(?m)^[ \t>*-]*"
    r"(?:[\[(]?" + _TIME + r"[\])]?[ \t]*(?:-[ \t]*)?)?"
    r"\**(?P<name>[^\W\d_][\w'’.\-]*(?:[ \t][\w'’.\-]+){0,3}?)\**"
    r"(?:[ \t]*[\[(]" + _TIME + r"[\])])?"
    r"[ \t]*:(?=[ \t]|$)")
_VTT = re.compile(r"<v(?:\.[\w.-]+)?[ \t]+(?P<name>[^>\n]{1,60})>")

#: Words that make a label a role, not a person.
GENERIC = {
    "agent", "customer", "caller", "client", "advisor", "adviser", "operator", "rep",
    "representative", "support", "helpdesk", "interviewer", "interviewee", "host", "guest",
    "moderator", "facilitator", "participant", "respondent", "speaker", "spk", "unknown",
    "system", "bot", "assistant", "ai", "user", "me", "you", "them", "other", "presenter",
    "chair", "panellist", "panelist", "audience", "member", "staff", "team", "manager",
    "supervisor", "engineer", "technician", "teacher", "parent", "student", "pupil",
    "doctor", "nurse", "patient", "officer", "lawyer", "solicitor", "witness", "judge",
    "coach", "tutor", "learner", "caseworker", "volunteer", "receptionist", "visitor",
}
#: Labels at the start of a line that are not speakers: headings and form fields.
NOT_SPEAKERS = {
    "subject", "from", "to", "cc", "bcc", "date", "time", "re", "fw", "fwd", "note", "notes",
    "action", "actions", "agenda", "summary", "attendees", "apologies", "present",
    "absent", "location", "venue", "ref", "reference", "tel", "phone", "mobile", "email",
    "address", "name", "password", "username", "status", "error", "warning", "info",
    "debug", "trace", "fatal", "question", "answer", "q", "a", "update", "outcome",
    "decision", "decisions", "next steps", "owner", "due", "priority", "issue", "problem",
    "resolution", "result", "results", "example", "examples", "step", "steps", "tip",
    "warning", "caution", "important", "nb", "ps", "pps", "edit", "update", "source",
    "sources", "title", "description", "type", "category", "item", "items", "total",
    "comments", "comment", "feedback", "minutes", "chair", "purpose", "background",
    "context", "objective", "objectives", "goal", "goals", "risk", "risks", "dear", "hi",
    "hello", "thanks", "regards", "best", "kind regards", "transcript", "call", "meeting",
    "recording", "duration", "start", "end", "started", "ended", "channel", "queue",
}


@dataclass(frozen=True)
class Speaker:
    """One speaker label: where its name sits in the text, the name, and whether it is a
    role ("Agent") rather than a person."""
    start: int
    end: int
    name: str
    generic: bool


def is_generic(label):
    """True when a label names a role: every word is a role word, a number, or a short
    code ("Speaker 1", "SPEAKER_01", "Caller B", "P2")."""
    words = [w for w in re.split(r"[\s_.\-]+", fold(label)) if w]
    if not words:
        return True
    return all(w in GENERIC or w.isdigit() or re.fullmatch(r"[a-z]?\d{1,3}|[a-z]", w)
               for w in words)


def _looks_named(label, is_name):
    """A person's name: one to four words, each with a capital (or a lower-case surname
    particle), or a lower-case label the caller recognises as a name."""
    words = label.split()
    if all(w[:1].isupper() or w.lower() in ("van", "der", "de", "da", "al", "bin", "le", "la")
           for w in words) and any(w[:1].isupper() for w in words):
        return True
    return bool(is_name and is_name(label))


def speakers(text, is_name=None):
    """Every speaker label in ``text``, one per line at most, in order. ``is_name`` is a
    test for a lower-case label ("priya:"), such as a first-name list lookup; without it
    only capitalised labels count as names."""
    found = []
    for match in _LABEL.finditer(text):
        name = match.group("name").strip().rstrip(".")
        folded = fold(name)
        if not name or folded in NOT_SPEAKERS:
            continue
        generic = is_generic(name)
        if not generic and (folded in core._FORM_WORDS or not _looks_named(name, is_name)):
            continue
        start = match.start("name")
        found.append(Speaker(start, start + len(name), name, generic))
    for match in _VTT.finditer(text):
        name = match.group("name").strip()
        start = match.start("name")
        found.append(Speaker(start, start + len(name), name, is_generic(name)))
    return sorted(found, key=lambda s: s.start)


_HONORIFIC = re.compile(r"(?i)\A(?:mr|mrs|ms|miss|mx|dr|prof|professor|sir|dame)\.?\s+")


_SURNAME = re.compile(r"[ \t]+((?:[A-Z][a-z\u00e0-\u00ff'\u2019]+)(?:-[A-Z][a-z\u00e0-\u00ff'\u2019]+)?)")


def fuller(name, text, is_word=None):
    """A one-word speaker name with the surname the transcript gives it once ("DANIEL"
    and "it's Daniel Okafor" make "Daniel Okafor"), or the name as it was. ``is_word``
    says a capitalised word after the name is an ordinary word, not a surname."""
    if " " in name.strip():
        return name
    for match in re.finditer(r"(?i)(?<![\w])" + re.escape(name) + r"(?![\w])", text):
        after = _SURNAME.match(text, match.end())
        if after and not (is_word and is_word(after.group(1))):
            return "%s %s" % (match.group(0) if not match.group(0).isupper()
                              else match.group(0).title(), after.group(1))
    return name


def named_speakers(text, is_name=None, is_word=None):
    """The distinct names of the speakers who are people, titles taken off, a one-word
    name widened to the fuller name the transcript gives (see :func:`fuller`), and a
    lone first name dropped when a longer name starts with it ("Priya", "Priya Shah")."""
    names = []
    for speaker in speakers(text, is_name):
        if speaker.generic:
            continue
        name = _HONORIFIC.sub("", speaker.name).strip()
        if name and " " not in name:
            name = fuller(name, text, is_word)
        if name and fold(name) not in {fold(n) for n in names}:
            names.append(name)
    folded = [fold(n) for n in names]
    return [n for n, f in zip(names, folded)
            if not (" " not in f and any(o != f and o.split()[0] == f for o in folded))]


# --- role cues -------------------------------------------------------------------
_ITEM = re.compile("(?P<token>%s)|(?P<word>[^\\W_]+(?:['’][^\\W_]+)*)|(?P<stop>[.!?;\\n])"
                   % core.TOKEN.pattern)


def cue_roles(text, mapping, cues, *, window=4, kinds=("PERSON",)):
    """``({token: role}, [(start, end, role, cue)])`` for name tokens in ``text`` (the
    scrubbed text with tokens) that have a cue word within ``window`` words in the same
    sentence. ``cues`` maps a role to its cue words or phrases ({"child": ["son",
    "daughter"]}). Only tokens of ``kinds`` and issued by ``mapping`` are read. The
    first role whose cue is found wins; a person keeps the role for every mention."""
    if not cues:
        return {}, []
    issued = mapping.issued()
    items = []          # (type, folded text or token, start, end)
    for match in _ITEM.finditer(text):
        if match.group("token"):
            items.append(("token", match.group("token"), match.start(), match.end()))
        elif match.group("word"):
            items.append(("word", fold(match.group("word")), match.start(), match.end()))
        else:
            items.append(("stop", "", match.start(), match.end()))
    patterns = [(role, [(cue, re.compile(r"(?<!\S)" + r"\s+".join(
        re.escape(fold(w)) for w in cue.split()) + r"(?!\S)")) for cue in words])
        for role, words in cues.items()]
    roles, hits = {}, []
    for i, (kind, value, start, end) in enumerate(items):
        if kind != "token" or value not in issued or core.kind_of(value) not in kinds:
            continue
        sides = [" ".join(w for w in _side(items, i, step, window) if w) for step in (-1, 1)]
        for role, compiled in patterns:
            cue = next((c for c, p in compiled if any(p.search(s) for s in sides)), None)
            if cue is not None:
                roles.setdefault(value, role)
                hits.append((start, end, roles[value], cue))
                break
    return roles, hits


def _side(items, i, step, window):
    """The words within ``window`` items of item i on one side, stopping at a sentence
    end, in reading order. A token counts towards the window and reads as nothing."""
    out, j = [], i + step
    while 0 <= j < len(items) and len(out) < window and items[j][0] != "stop":
        out.append(items[j][1] if items[j][0] == "word" else "")
        j += step
    return out if step > 0 else out[::-1]
