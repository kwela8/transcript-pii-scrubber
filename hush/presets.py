"""Five presets, each a fixed set of choices, and the one call that runs them.

    from hush import Hush
    h = Hush("share", config="examples/support-call/hush.toml")
    result = h.scrub(text)
    if result.refused: ...            # the second check found something: do not send
    print(result.text)

Every preset finds the same way: the names to keep, known people, the first-name list,
the caller's own detectors, identifiers from the packs, the capitalised-name guess (all
but ``logs``). They differ in what a found value becomes and in how strict the second
check is.

========  ===========  ======================================================
preset    becomes      when
========  ===========  ======================================================
ask-ai    tokens       sending a transcript, ticket, email or note to an AI
                       model; the answer comes back with the real values put back
share     labels       pasting into a chat, a ticket, a slide, a case study, a
                       bug report; "[person 1]", "[email 2]"
dataset   pseudonyms   an export for an analyst or researcher; the same person
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
from pathlib import Path

from hush import core, quasi, residual, transcripts
from hush.config import Config, load
from hush.people import People, Person, english_words, keep_guess
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
    Preset("ask-ai", "Send a transcript, ticket, email or note to an AI model and read its "
           "answer with the real values put back.", "token"),
    Preset("share", "Paste into a chat, a ticket, a slide or a case study, or file a bug "
           "report: readable labels, one way.", "label", any_case=True),
    Preset("dataset", "Hand an export to an analyst or researcher: the same person is the "
           "same code in every file run with the same key.", "pseudonym", check="warn"),
    Preset("demo", "Training material, demos and test fixtures: made-up names in the real "
           "ones' places.", "fake", check="warn"),
    Preset("logs", "Logs and error reports sent to an outside tool: no capitalised-name guess, "
           "names in any case.", "label", any_case=True, guess=False),
)}

_OVERRIDES = {"names", "any_case", "guess", "check", "style", "rules", "guess_filter"}


@dataclass
class Result:
    """One scrub. ``text`` is what may leave; it is empty when ``refused``.

    ``removed`` counts the distinct values taken out, by kind; ``findings`` counts what
    the second check found, by kind; ``flags`` lists what a person should look at: the
    values of flagged kinds left in the text, and names a role cue relabelled. Each flag
    gives a kind, where it sits in ``text`` and why, never the value itself. ``quasi``
    counts details left in ``text`` that may identify someone together (ages, places,
    jobs, dates, rare details; :mod:`hush.quasi`), and ``warnings`` says so when they
    reach the config's ``[warn] quasi`` threshold. Neither removes anything."""
    text: str
    preset: Preset
    removed: dict
    findings: dict
    refused: bool
    mapping: core.Mapping = field(repr=False)
    tokens: str = field(repr=False, default="")
    flags: list = field(default_factory=list)
    quasi: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def restore(self, reply):
        """Put the real words back into an AI's reply. ``ask-ai`` only, same process."""
        if not self.preset.reversible:
            raise ValueError("hush: only the ask-ai preset can be restored")
        return core.restore(reply, self.mapping)

    def restore_report(self, reply):
        return core.restore_report(reply, self.mapping)


class Hush:
    """One use case. Build once, call :meth:`scrub` many times: the labels, pseudonyms
    and fakes stay the same across calls.

    ``preset`` names one of ``PRESETS``; without it the config's preset is used, else
    ``share``. ``config`` is a :class:`hush.config.Config` or the path of a config file.
    ``people`` is a list of :class:`hush.people.Person` to remove, on top of the config's;
    ``keep`` a list of people (or names) never to remove. ``roster`` is the older name for
    ``people``, and ``staff`` adds people with the role "staff". ``key`` (bytes) makes
    pseudonyms and fakes the same across runs; without it they are the same within this
    object only. Any of ``names``, ``any_case``, ``guess``, ``check`` and ``style``
    overrides the preset and the config. ``rules=False`` and ``guess_filter=False`` turn
    off the titled-name and login rules and the guess filter, for measuring.
    """

    def __init__(self, preset=None, *, config=None, people=(), keep=(), roster=(), staff=(),
                 key=None, **overrides):
        if isinstance(config, (str, Path)):
            config = load(config)
        self.config = config or Config()
        name = preset or self.config.preset or "share"
        if name not in PRESETS:
            raise ValueError("hush: preset must be one of %s" % ", ".join(PRESETS))
        unknown = set(overrides) - _OVERRIDES
        if unknown:
            raise ValueError("hush: unknown option %s" % ", ".join(sorted(unknown)))
        settings = {k: v for k, v in (("names", self.config.names),
                                      ("any_case", self.config.any_case),
                                      ("guess", self.config.guess),
                                      ("check", self.config.check)) if v is not None}
        settings.update({k: v for k, v in overrides.items() if k not in ("rules", "guess_filter")})
        self.preset = replace(PRESETS[name], **settings)
        if self.preset.check not in ("refuse", "warn", "off"):
            raise ValueError("hush: check must be refuse, warn or off")
        self.guess_filter = overrides.get("guess_filter", True)
        known = list(self.config.known) + list(people) + list(roster) + [
            replace(p, role=p.role or "staff") for p in staff]
        self.people = People(
            known, list(self.config.keep) + list(keep), names=self.preset.names,
            any_case=self.preset.any_case, role=self.config.role,
            keep_words=self.config.keep_words, patterns=self.config.detectors,
            login_labels=self.config.login_labels, columns=self.config.columns,
            first_names=self.config.first_names, rules=overrides.get("rules", True))
        labels = {**self.people.labels, **self.config.labels}
        self.renderer = Renderer(self.preset.style, key=key, who=self.people.who,
                                 exclude=self.people.names_on_list, labels=labels,
                                 leave={"KEEP", *self.config.flag})

    def __repr__(self):
        return "Hush(%s, %r)" % (self.preset.name, self.people)

    def _speakers(self, text):
        """The people this transcript's speaker labels add, as (known, keep)."""
        mode = self.config.speakers
        if mode == "text":
            return (), ()
        people = self.people

        def is_name(label):
            words = label.split()
            return bool(words) and all(core.fold(w) in people.first_names or
                                       core.fold(w) in people.names_on_list for w in words[:1])
        def is_word(word):
            folded = core.fold(word)
            return folded in people.keep or folded in english_words() or \
                folded in core._FORM_WORDS

        names = transcripts.named_speakers(text, is_name, is_word)
        if mode == "keep":
            return (), [Person.from_name(n) for n in names]
        roles = {core.fold(k): v for k, v in self.config.speaker_roles.items()}
        return [Person.from_name(n, roles.get(core.fold(n), "speaker")) for n in names], ()

    def scrub(self, text, mapping=None, *, people=(), keep=()):
        """Scrub one text. ``people`` and ``keep`` add known people and names to keep for
        this text only: the customer and the agent on one call, from its metadata."""
        spoken_known, spoken_keep = self._speakers(text)
        call = self.people.with_people(list(people) + list(spoken_known),
                                       list(keep) + list(spoken_keep))
        tokens, mapping = core.scrub(
            text, mapping, packs=self.config.packs, keep=self.people.keep_words,
            people=call.detector, heuristic_names=self.preset.guess,
            guess_filter=keep_guess if self.guess_filter else None, years=self.config.years)
        roles, cued = transcripts.cue_roles(tokens, mapping, self.config.cues,
                                            window=self.config.cue_window)
        leave = self.renderer.leave
        removed, seen = {}, set()
        for match in core.TOKEN.finditer(tokens):
            token = match.group(0)
            if token in seen or token not in mapping.by_token:
                continue
            seen.add(token)
            kind = core.role_kind(roles[token]) if token in roles else match.group("kind")
            if kind in leave or match.group("kind") in leave:
                continue
            removed[kind] = removed.get(kind, 0) + 1
        found = {} if self.preset.check == "off" else \
            residual.check(tokens, mapping, packs=self.config.packs)["found"]
        refused = bool(found) and self.preset.check == "refuse"
        flags = []
        if refused:
            out = ""
        else:
            if call is not self.people:
                self.renderer.exclude |= call.names_on_list
            out, spans = self.renderer.render_spans(tokens, mapping, who=call.who, roles=roles)
            cue_of = {}
            for start, end, role, cue in cued:
                cue_of.setdefault(tokens[start:end], cue)
            for start, end, kind, token in spans:
                if token in roles:
                    flags.append({"kind": kind, "start": start, "end": end,
                                  "why": "role cue: %s" % cue_of.get(token, "")})
                elif kind in self.config.flag:
                    flags.append({"kind": kind, "start": start, "end": end,
                                  "why": "flagged kind, left in place"})
        details = quasi.count(out) if out else {}
        warned = quasi.warning(details, self.config.quasi)
        return Result(out, self.preset, removed, found, refused, mapping, tokens, flags,
                      details, [warned] if warned else [])
