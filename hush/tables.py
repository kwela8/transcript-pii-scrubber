"""A CSV export, column by column: the columns that hold people are replaced by kind, and
every other text column is scrubbed like prose with the same class list.

A column's kind comes from its header (``hush.students.column_role`` and the extra names
below). The export's own name columns join the class list first, so a comment column
that says "Aisha has improved" loses Aisha even with no class list given.

What each column becomes, by style:

==============  ===================  ==================  =================
column          label                pseudonym           fake
==============  ===================  ==================  =================
forename        [student 3]          Pupil-3F9A1C        a made-up name
surname         (emptied)            (emptied)           a made-up surname
full name       [student 3]          Pupil-3F9A1C        a made-up name
username, UPN,  [UPN 3]              UPN-81D2E0          a label
ULN, email
date of birth   year only            year only           year only
postcode        outward code only    outward code only   outward code only
phone, address  [phone 1]            PHONE-...           a drama-range number
other text      scrubbed as prose    scrubbed as prose   scrubbed as prose
numbers, dates  unchanged            unchanged           unchanged
==============  ===================  ==================  =================

A pupil's code is keyed on the pupil (forename and surname), so the forename column and a
mention of the pupil in a comment column carry the same code.
"""
from __future__ import annotations

import csv
import io
import re


from hush.presets import Hush
from hush.students import Person, column_role, fold

_EXTRA_ROLES = {
    "dob": {"dob", "date_of_birth", "birth_date", "birthdate", "d_o_b"},
    "postcode": {"postcode", "post_code", "postal_code", "zip"},
    "phone": {"phone", "telephone", "tel", "mobile", "phone_number", "contact_number",
              "parent_phone", "home_phone"},
    "address": {"address", "street", "address_1", "address1", "address_line_1",
                "address_line_2", "home_address", "town", "house"},
    "parent": {"parent", "parent_name", "carer", "carer_name", "guardian", "contact_name",
               "mother", "father", "parent_carer"},
    "parent_email": {"parent_email", "carer_email", "contact_email"},
}
_YEAR = re.compile(r"(?:19|20)\d{2}")
_OUTWARD = re.compile(r"(?i)\A\s*([A-Z]{1,2}\d[A-Z\d]?)\s*\d[A-Z]{2}\s*\Z")
_NUMERIC = re.compile(r"\A[\s\d.,:/%+\-£$€]*\Z")


def role_of(header):
    role = column_role(header)
    if role:
        return role
    key = re.sub(r"[\s\-]+", "_", fold(header.strip()))
    for name, keys in _EXTRA_ROLES.items():
        if key in keys:
            return name
    return None


def scrub_csv(text, preset="dataset", *, roster=(), staff=(), key=None, delimiter=None):
    """Scrub one CSV held as a string; return ``(csv_text, report)``. ``report`` has the
    columns by role and the counts of what the free-text cells lost."""
    dialect_delim = delimiter or _sniff(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=dialect_delim))
    if not rows:
        return text, {"columns": {}, "removed": {}}
    header = rows[0]
    roles = [role_of(h) for h in header]
    people = []
    for row in rows[1:]:
        got = {r: (row[i].strip() if i < len(row) else "") for i, r in enumerate(roles)
               if r in ("first", "last", "preferred", "full", "username", "email", "upn", "uln")}
        got = {k: v for k, v in got.items() if v}
        if "full" in got and not ("first" in got or "last" in got):
            first, _, last = got.pop("full").rpartition(" ")
            got["first"], got["last"] = (first or last), (last if first else "")
        got.pop("full", None)
        if got.get("first") or got.get("last"):
            people.append(Person(**got))
    hush = Hush(preset, roster=list(roster) + people, staff=staff, key=key)
    render = hush.renderer
    removed = {}
    out = io.StringIO()
    writer = csv.writer(out, delimiter=dialect_delim, lineterminator="\n")
    writer.writerow(header)
    for index, row in enumerate(rows[1:]):
        person = people[index] if index < len(people) else None
        new = []
        for i, cell in enumerate(row):
            role = roles[i] if i < len(roles) else None
            new.append(_cell(cell, role, person, hush, render, removed))
        writer.writerow(new)
    report = {"columns": {h: r for h, r in zip(header, roles) if r},
              "people": len(people), "removed": removed, "style": hush.preset.style}
    return out.getvalue(), report


def _sniff(text):
    first = text.split("\n", 1)[0]
    return max(("\t", ",", ";", "|"), key=first.count)


def _cell(cell, role, person, hush, render, removed):
    value = cell.strip()
    if not value:
        return cell
    style = hush.preset.style
    if role in ("first", "full", "preferred"):
        kind = "STUDENT"
        real = (" ".join(p for p in (person.first, person.last) if p) if person else value)
        return _name(render, style, kind, real, value)
    if role == "last":
        return render.fake_surname(value) if style == "fake" else ""
    if role == "parent":
        return _name(render, style, "PERSON", value, value)
    if role in ("username", "email", "upn", "uln", "parent_email", "phone"):
        kind = {"username": "USERNAME", "email": "EMAIL", "upn": "UPN", "uln": "ULN",
                "parent_email": "EMAIL", "phone": "PHONE"}[role]
        if style == "token":
            return "[%s]" % kind.lower()
        return render.value(kind, value)
    if role == "dob":
        year = _YEAR.search(value)
        return year.group(0) if year else ""
    if role == "postcode":
        outward = _OUTWARD.match(value)
        return outward.group(1).upper() if outward else ""
    if role == "address":
        return "[address]"
    if _NUMERIC.match(value):
        return cell
    result = hush.scrub(cell)
    for kind, n in result.removed.items():
        removed[kind] = removed.get(kind, 0) + n
    return result.text if not result.refused else "[withheld]"


def _name(render, style, kind, real, shown):
    if style == "token":
        return "[%s]" % kind.lower()
    if style == "fake":
        fake = render.value(kind, real)
        return fake.split()[0] if len(real.split()) > 1 and len(shown.split()) == 1 else fake
    return render.value(kind, real)


def scrub_file(src, dest, preset="dataset", **kwargs):
    with open(src, newline="", encoding="utf-8-sig") as handle:
        text = handle.read()
    out, report = scrub_csv(text, preset, **kwargs)
    with open(dest, "w", newline="", encoding="utf-8") as handle:
        handle.write(out)
    return report


__all__ = ["scrub_csv", "scrub_file", "role_of"]
