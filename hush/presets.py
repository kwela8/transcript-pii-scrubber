"""Five scenarios, each a fixed set of choices, and the one call that runs them.

    from hush import Hush, read_roster
    h = Hush("share", roster=read_roster("9X.csv"))
    result = h.scrub(text)
    if result.refused: ...            # the second check found something: do not send
    print(result.text)

Every preset finds the same way: roster, first-name list, identifiers by shape, the
capitalised-name guess (all but ``logs``). They differ in what a found value becomes and
in how strict the second check is.

========  ===========  ======================================================
preset    becomes      when
========  ===========  ======================================================
ask-ai    tokens       sending a ticket, email or note to an AI model; the
                       answer comes back with the real names put back
share     labels       pasting into Slack, Jira, a slide, a case study, a bug
                       report; "[student 1]", "[staff 2]"
dataset   pseudonyms   an export for an analyst or researcher; the same pupil
                       is the same code in every file run with the same key
demo      fakes        training material, demos, test fixtures; made-up names
                       in the real ones' places
logs      labels       logs and error reports sent to an outside tool; no
                       capitalised-name guess (class names would trip it),
                       names matched in any case
========  ===========  ======================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from hush import core, residual
from hush.students import Pupils, keep_guess
from hush.styles import Renderer


@dataclass(frozen=True)
class Preset:
    name: str
    use: str
    style: str
    names: bool = True          # the first-name list
    any_case: bool = False      # first-name-list names in lower case and capitals too
    guess: bool = True          # the core's capitalised-name guess
    check: str = "refuse"       # the second check: "refuse", "warn" or "off"

    @property
    def reversible(self):
        return self.style == "token"


PRESETS = {p.name: p for p in (
    Preset("ask-ai", "Send a ticket, email or note to an AI model and read its answer with "
           "the real names put back.", "token"),
    Preset("share", "Paste into Slack, Jira, a slide or a case study, or file a bug report: "
           "readable labels, one way.", "label", any_case=True),
    Preset("dataset", "Hand an export to an analyst or researcher: the same pupil is the same "
           "code in every file run with the same key.", "pseudonym", check="warn"),
    Preset("demo", "Training material, demos and test fixtures: made-up names in the real "
           "ones' places.", "fake", check="warn"),
    Preset("logs", "Logs and error reports sent to an outside tool: no capitalised-name guess, "
           "names in any case.", "label", any_case=True, guess=False),
)}


@dataclass
class Result:
    """One scrub. ``text`` is what may leave; it is empty when ``refused``."""
    text: str
    preset: Preset
    removed: dict
    findings: dict
    refused: bool
    mapping: core.Mapping = field(repr=False)
    tokens: str = field(repr=False, default="")

    def restore(self, reply):
        """Put the real words back into an AI's reply. ``ask-ai`` only, same process."""
        if not self.preset.reversible:
            raise ValueError("hush: only the ask-ai preset can be restored")
        return core.restore(reply, self.mapping)

    def restore_report(self, reply):
        return core.restore_report(reply, self.mapping)


class Hush:
    """One scenario for one school's text. Build once, call :meth:`scrub` many times: the
    labels, pseudonyms and fakes stay the same across calls.

    ``roster`` and ``staff`` are lists of :class:`hush.students.Person`
    (:func:`hush.students.read_roster` reads a class-list CSV). ``key`` (bytes) makes
    pseudonyms and fakes the same across runs; without it they are the same within this
    object only. Any of ``names``, ``any_case``, ``guess`` and ``check`` overrides the
    preset."""

    def __init__(self, preset="share", *, roster=(), staff=(), key=None, **overrides):
        if preset not in PRESETS:
            raise ValueError("hush: preset must be one of %s" % ", ".join(PRESETS))
        unknown = set(overrides) - {"names", "any_case", "guess", "check", "style"}
        if unknown:
            raise ValueError("hush: unknown option %s" % ", ".join(sorted(unknown)))
        self.preset = replace(PRESETS[preset], **overrides)
        if self.preset.check not in ("refuse", "warn", "off"):
            raise ValueError("hush: check must be refuse, warn or off")
        self.pupils = Pupils(roster, staff, names=self.preset.names,
                             any_case=self.preset.any_case)
        self.renderer = Renderer(self.preset.style, key=key, who=self.pupils.who,
                                 exclude=self.pupils.known)

    def __repr__(self):
        return "Hush(%s, %r)" % (self.preset.name, self.pupils)

    def scrub(self, text, mapping=None):
        tokens, mapping = core.scrub(text, mapping, students=self.pupils.detector,
                                     heuristic_names=self.preset.guess,
                                     guess_filter=keep_guess)
        removed = {}                      # distinct values taken out, by kind
        for token in mapping.issued():
            if token in tokens:
                kind = core.kind_of(token)
                removed[kind] = removed.get(kind, 0) + 1
        found = {} if self.preset.check == "off" else residual.check(tokens, mapping)["found"]
        refused = bool(found) and self.preset.check == "refuse"
        out = "" if refused else self.renderer.render(tokens, mapping)
        return Result(out, self.preset, removed, found, refused, mapping, tokens)
