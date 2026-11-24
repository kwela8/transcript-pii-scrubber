"""Details that identify no one alone but may together: an age, a place, a job, a date,
a rare detail. Counted on the text that leaves, after the scrub, so what was taken out
does not count. Nothing here removes anything; :class:`hush.Hush` turns a count above
the config's threshold into a warning.

The rules are short lists and plain shapes. They count what they see, which is a prompt
to read the text again, not a measure of how identifying it is."""

from __future__ import annotations

import re

from hush import core

_AGE = re.compile(
    r"(?i)\b(?:aged|age[d:]?)[ \t]*\d{1,3}\b|\b\d{1,3}[ -]?(?:years?|yrs?)[ -]?old\b|"
    r"\bin[ \t]+(?:his|her|their|my)[ \t]+(?:early[ \t]+|mid[ \t-]?|late[ \t]+)?"
    r"(?:teens|twenties|thirties|forties|fifties|sixties|seventies|eighties|nineties)\b")
_JOBS = (
    "accountant", "actor", "architect", "baker", "barber", "barista", "bricklayer",
    "builder", "butcher", "carer", "carpenter", "cashier", "chef", "cleaner", "councillor",
    "dentist", "designer", "developer", "doctor", "driver", "electrician", "engineer",
    "farmer", "firefighter", "gardener", "hairdresser", "headteacher", "journalist",
    "judge", "labourer", "lawyer", "lecturer", "librarian", "manager", "mechanic",
    "midwife", "nurse", "optician", "paramedic", "pharmacist", "photographer",
    "physiotherapist", "pilot", "plumber", "police officer", "postman", "priest",
    "professor", "programmer", "receptionist", "researcher", "scientist", "secretary",
    "shopkeeper", "social worker", "soldier", "solicitor", "surgeon", "surveyor",
    "teacher", "technician", "therapist", "vet", "waiter", "waitress", "writer")
_JOB = re.compile(r"(?i)\b(?:" + "|".join(j.replace(" ", r"[ \t]+") for j in _JOBS)
                  + r")s?\b")
# A capitalised place after a word that places someone: "from Leeds", "moved to Hollow
# Bay", "lives in Ashcombe".
_PLACE = re.compile(
    r"\b(?:from|in|near|to|at|of)[ \t]+(?:the[ \t]+)?"
    r"(?P<place>[A-Z][a-z]+(?:[ \t-][A-Z][a-z]+){0,2})\b")
_NOT_PLACES = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday", "english", "maths", "science", "the", "a", "an",
    "year", "term", "school", "class", "christmas", "easter", "spring", "summer", "autumn",
    "winter", "i", "he", "she", "they", "we", "you", "it", "this", "that", "mr", "mrs",
    "ms", "dr", "miss"}
_DATE = re.compile(
    r"(?<![\w.,/:-])(?:19|20)\d{2}(?![\w%]|[.,:/-]\d)|\b(?:January|February|March|April|"
    r"June|July|August|September|October|November|December)\b|\b(?:Monday|Tuesday|"
    r"Wednesday|Thursday|Friday|Saturday|Sunday)\b")
_RARE = re.compile(
    r"(?i)\bdiagnosed[ \t]+with\b|\brare\b|\bthe[ \t]+only[ \t]+(?:one|person|woman|man|"
    r"girl|boy|child|pupil|member)\b|\b\d[ \t]?(?:ft|foot|feet)(?:[ \t]+\d{1,2}(?:[ \t]?in)?)?"
    r"(?:[ \t]+tall)?\b|\b\d{3}[ \t]?cm[ \t]+tall\b|\b\d{2,3}[ \t]?(?:kg|lb|lbs|stone)\b|"
    r"\btattoos?\b|\bwheelchair\b|\btwins?\b|\btriplets\b|\bamputee\b")


def count(text):
    """``{kind: n}`` for the details in ``text`` outside hush's tokens and labels."""
    plain = core.TOKEN.sub(" ", text)
    plain = re.sub(r"\[[a-z][a-z ]* \d+\]", " ", plain)
    found = {}

    def add(kind, n):
        if n:
            found[kind] = found.get(kind, 0) + n

    add("age", len(_AGE.findall(plain)))
    add("job", len(_JOB.findall(plain)))
    add("place", sum(1 for m in _PLACE.finditer(plain)
                     if m.group("place").split()[0].lower() not in _NOT_PLACES))
    add("date", len(_DATE.findall(plain)))
    add("rare", len(_RARE.findall(plain)))
    return found


def warning(found, threshold):
    """A warning line when the details reach ``threshold`` (0 turns it off), else None."""
    total = sum(found.values())
    if not threshold or total < threshold:
        return None
    return ("this text still holds %d details that together may identify someone (%s); "
            "nothing was removed for them" % (
                total, ", ".join("%s %d" % (k, found[k]) for k in sorted(found))))
