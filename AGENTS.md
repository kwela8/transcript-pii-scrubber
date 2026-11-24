# AGENTS.md

Guidance for an AI coding agent working in this repository. Read this file, then
`docs/explainer.html` and `docs/transcripts-plan.html`, before you change anything.

The repository holds a working, measured tool: the Python package `hush` (version 0.2.0,
standard library only, MIT licence). It checks a transcript or any other text for the kinds
of personal data a config chooses, and replaces them before the text goes to an AI model, a
chat, a dataset or a log. The next piece of work it is set up for is a model pass for call
transcripts, specified below and in `docs/transcripts-plan.html`. You are extending a
measured design, not inventing one.

## What is here

| Path | What it is |
|---|---|
| `hush/core.py` | Tokens and restore, the identifier rules in packs, the general vocabulary (`KEEP`) and the capitalised-name guess |
| `hush/people.py` | The people layer: known people, names to keep, the first-name list, name-words, logins, your own detectors, screenshot misreads, and the guess filter `keep_guess` |
| `hush/transcripts.py` | Speaker labels and role cues |
| `hush/config.py` | The config file, TOML or JSON |
| `hush/residual.py` | The second check, written apart from the detectors |
| `hush/presets.py` | The five presets, `Hush` and `Result` |
| `hush/styles.py` | What a found value becomes: token, label, pseudonym or fake |
| `hush/tables.py` | CSV exports, column by column |
| `hush/__main__.py` | The command line |
| `hush/lists/*.txt` | First names (ONS, England and Wales), name-words, common names with sex, English words (SCOWL) |
| `tools/build_names.py` | Rebuilds the lists from the ONS workbook and a word list |
| `bench/bench.py` | The bench, for any test set and any config |
| `bench/general/cases.json` | A made-up general set: 41 texts, 12 with no personal data |
| `bench/education/cases_*.json` | Three made-up school sets: 290 cases, 1,361 pupil-name sightings, 95 name-free texts |
| `examples/support-call/` | A config, an agents keep list and a call transcript |
| `examples/llm-document/` | A config and meeting notes for the `ask-ai` round trip |
| `examples/education/` | A config that reproduces hush 0.1.0's school behaviour, a class list, a ticket, an export |
| `tests/test_hush.py` | Unit tests |
| `docs/explainer.html` | What the tool does and how well, for people |
| `docs/transcripts-plan.html` | The design for call transcripts, with the research behind it |
| `NOTICE`, `licences/` | Where the lists come from and their licences |

Every name in the repository is made up.

## Commands

Run everything from the repository root.

```
python3 -m unittest discover -s tests
python3 bench/bench.py bench/general/cases.json
python3 bench/bench.py bench/education/cases_1.json --config examples/education/hush.toml
python3 bench/bench.py bench/education/cases_2.json --config examples/education/hush.toml
python3 bench/bench.py bench/education/cases_3.json --config examples/education/hush.toml
python3 -m hush scrub --config examples/support-call/hush.toml examples/support-call/call.txt
```

Run the tests and all four bench runs before and after every change, and compare the
figures with the ones under "How to measure".

## Ground rules

1. Transcripts, tickets and notes about real people are personal data. Do not paste real
   ones into a chat, a test file or any outside API unless the data protection lead of the
   organisation that owns them has approved that route (a contract that rules out
   training, a region, a retention limit). Build and test on made-up sets first.
2. Logs, reports and errors carry counts only, never a removed value. `Result.removed`
   counts by kind and `Result.flags` gives kinds and positions; neither holds a value. Keep
   it that way.
3. Keep a second check that is written separately from the detectors and reads only the
   output (`hush/residual.py`). If it still finds an identifier shape, the default is to
   refuse, not to warn.
4. Keep one test set unseen while you tune, and report the unseen figure as the real one.
   Education set 3 is held out. The general set was used to fix two faults after its first
   run, so it no longer counts as fully held out; write a new one before tuning general
   behaviour, and say so.
5. A name the tool cannot place is flagged for a person to look at. It is never silently
   kept.
6. Standard library only, no network, and nothing written to disk unless the caller asks.
7. Use-case vocabulary, identifiers and column names go in a config, not the core. The
   education example is the pattern: what hush 0.1.0 had built in for schools is now
   `examples/education/`.

## The design in the code

### Tokens and restore

Each found value becomes a token `<P{16 hex}_{KIND}_{NNNN}_{16 hex check}>`
(`hush/core.py`, `TOKEN`). The first 16 hex digits are a per-run namespace, NNNN counts per
kind, and the check is an HMAC of the value under a per-run key, so a forged token is never
restored. The value-to-token map lives in memory only. Restore replaces only exact issued
tokens and counts anything token-shaped that was not issued. For name kinds (PERSON,
CLINICIAN, PLACE and every `PERSON_<ROLE>`) the same person in any case gets one token, so a
model sees one person once; restore gives back the first casing seen. A kept name becomes a
`KEEP` token during the scrub and is put back as written in every style.

### Packs

Every identifier rule in `hush/core.py` carries a pack (`_Rule.pack`): `general`, `uk`,
`north-america` or `south-africa`. `core.scrub(packs=...)` runs the rules of the packs named
(default `DEFAULT_PACKS`: all but `south-africa`), and `hush/residual.py` maps each of its
checks to a pack (`_CHECK_PACKS`) so the second check reads for the same packs. A new
country's rules go in a new pack, with a line in `PACKS` and its checks tagged.

### The order of rules

Each step only looks at text outside the tokens already issued (`core.scrub`).

1. **Secret columns and emails and links**, whole (`general` pack).
2. **Names to keep** (`people._Keep`). Each kept person gives the full name in either
   order, a preferred name with the surname, each name alone, and a title with the surname
   or its initial. A lone kept surname straight after another capitalised name, and a lone
   kept first name straight before another surname, belong to someone else and are not
   kept. Keeping a person who is on the known list keeps their preferred names from it.
3. **The people step** (`People.find`). These are found together, and where two overlap
   the longer wins (`_no_overlaps`):
   - **Titled names.** `(Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Sir|Dame)\.? ` then one to three
     capitalised words (ASCII, Latin-1 and Latin Extended-A letters) or an initial and a
     surname, or the same in capitals. The title stays outside the token.
   - **Your own detectors** (`[[detectors]]` and `[[redact]]` in the config, `Detector` in
     Python), the first that matches a value naming its kind, then the known people's IDs,
     usernames and emails.
   - **Logins and handles.** Handles: `(?<![\w@.])@` then the handle, except `@here`,
     `@channel` and `@everyone`. Chat speakers at the start of a line shaped like a login.
     A value after a login label (`user`, `username`, `login`, `uid`, and the config's
     `login_labels`) when it looks like a login. Login shapes that start with a name:
     `name.x`, `namek3`, `mo_khan`.
   - **The known people.** Full name in either order (with a comma or a line break
     between), with possessives; preferred, first and last names alone in any case.
     Accents and case are folded before comparing (NFKD, combining marks dropped, lower
     case). A two-letter name alone needs its capital. A pasted table whose header has a
     First name, Surname or Name column (or a header the config's `columns` names) adds its
     rows for that text.
   - **Known names that are also English words** ("Grace", "Will", "Summer", "Mark"),
     taken with a capital only in a name's place, and in lower case only before a person
     verb or as a possessive.
   - **The first-name list** (`hush/lists/first_names.txt`, 22,643 names given to 10 or
     more babies in England and Wales, 1996 to 2025, that are not English words, plus the
     config's `[names] files`). Taken with a capital anywhere, and in lower case when the
     preset asks. Not straight after in, near, from, via and similar. A capitalised surname
     of up to two words may follow, with particles; in lower case, up to two following
     words that are not English words.
   - **A capitalised word that is not an English word** before a person verb.
   - **Screenshot misreads** of known names of six letters or more.
4. **JSON fields** and **numbers read out as words**, with double, triple and "nine
   hundred" (`general` pack).
5. **The packs' identifier rules**: labelled values first, then shapes, then every long
   number.
6. **The capitalised-name guess**, except protected words (`KEEP` and the config's
   `[words]`), then **the guess filter** (`keep_guess`): a run stands only when one word is
   not an English word, or it opens with a word-name given to 1,000 babies or more, or it
   is alone and not before you, this, the and similar, or it sits straight after a name
   already taken.
7. **The second check** reads the output only, for the packs that ran. Any hit refuses.

### Transcripts and flags

`hush/transcripts.py` finds speaker labels at line starts (with an optional time before or
after the name) and in WebVTT voice tags. Labels made only of role words, numbers and short
codes are generic and stay. `[transcript] speakers` is `text` (labels are text), `keep`
(named speakers become names to keep for that text) or `relabel` (named speakers become
known people with the role `[transcript] roles` gives, else "speaker"). A one-word label
takes the fuller name the transcript gives it.

`cue_roles` reads, for each name token, up to `window` words either side within the
sentence; the first `[cues]` role whose word or phrase is there relabels that person for the
whole text and adds a flag. Kinds in `flag` are put back as written and flagged. A flag is
`{"kind", "start", "end", "why"}`, positions in the output.

### Five presets

| Preset | Output | First-name list in any case | Guess | Second check |
|---|---|---|---|---|
| ask-ai | tokens, restored in the model's answer | no | on | refuse |
| share | `[person 1]`, `[customer 2]`, `[email 3]` | yes | on | refuse |
| dataset | `Person-3F9A1C` (HMAC of the person under a key) | no | on | warn |
| demo | made-up names of the same sex, `07700 900xxx` phones | no | on | warn |
| logs | labels | yes | off | refuse |

A config's `[names]` and `check` override the preset's choices. For CSV exports
(`hush/tables.py`): name columns become the person's label or code by role, contact columns
a person, ID columns the label of the config's detector they match, a date of birth keeps
its year, a postcode keeps its outward code, numbers stay, and every other text cell is
scrubbed with the export's own names as known people.

## How to measure

Each test case is JSON: `id`, `shape`, `text`, `roster` (first, last, preferred, role),
optional `keep` (first, last), and `spans` (value, kind, and for names `on_roster`: yes,
variant or no; kind `KEEP` for a name that must stay). Negatives are texts with no personal
data. A set may list `unscored` kinds. Scoring: a sighting is caught when none of its
letters or digits is left in place, aligning input and output with the tokens collapsed to
one character; a kept title is not a leak. A KEEP sighting is intact when all of it is left.
The bench reports by kind, by known-list status and by shape, with the negatives that lost a
word, extra names taken and exact restores.

Figures the current code gives. General set, no config, `share` preset:

| | general set |
|---|---|
| names | 88.5% (285 of 322) |
| on the known list | 99.0% (96 of 97) |
| nicknames, initials, reordered | 59.4% (19 of 32) |
| not on the known list | 88.1% (170 of 193) |
| kept names left whole | 100% (89 of 89) |
| texts with no personal data that lost a word | 3 of 12 |
| exact restores | 39 of 41 |

Education sets, `examples/education/hush.toml`, `share` preset (the same as hush 0.1.0):

| | set 1 (tuned on) | set 2 (tuned on) | set 3 (held out) |
|---|---|---|---|
| pupil names | 97.7% | 92.4% | 90.5% |
| pupils on the class list | 98.2% | 98.1% | 97.1% |
| nicknames, initials and misreads | 96.4% | 67.3% | 62.2% |
| adults | 99.3% | 90.1% | 95.9% |
| name-free texts that lost a word | 7 of 40 | 2 of 30 | 3 of 25 |
| exact restores | 150 of 150 | 79 of 80 | 58 of 60 |

A change that lowers any of these needs a reason in its commit message. A change that moves
an education figure at all needs one too: the education config is the record that 0.2.0
kept 0.1.0's behaviour.

## Transcripts: the next step

The job: call transcripts between an agent and a customer. Keep the agent and the customer,
remove every other person's name, and flag each by the role the words around it give.
`docs/transcripts-plan.html` has the reasons and sources; this is the specification.

Built already: speaker labels (`keep`, `relabel`), names to keep per call
(`Hush.scrub(text, keep=[...])`), known people per call (`people=[...]`), lower-case
speech-to-text names and numbers, role cues and flags, and the second check.

Not built:

1. **Fuzzy matching** of known and kept names up to two letters out for names of five
   letters or more, for transcription slips ("Katarzina").
2. **A local candidate model** (optional): a GLiNER model under Apache-2.0 (the urchade,
   knowledgator or fastino PII models) with one label, "person", at a low threshold, adding
   candidates; it never removes one.
3. **Model pass**, only on a route the data protection lead approved (for example the paid
   Gemini API or Vertex AI in London, `gemini-3.5-flash`, with logging and caching off).
   Send the partly scrubbed text in windows of about 40 turns overlapping by 5, with the
   speaker labels, the keep list, the config's roles and the numbered candidates still
   unresolved. Temperature 0. Five to ten worked examples in the prompt, including
   word-names ("Grace", "Will"), nicknames, initials, a colleague who is not a speaker, and
   a product named like a person that must stay. Require JSON against a schema:

   ```json
   {"candidates": [{"candidate_id": 3, "turn_id": 41, "quote": "callum",
                    "start": 12, "end": 18, "role": "family",
                    "decision": "redact", "reason": "my son callum"}],
    "missed": [{"turn_id": 44, "quote": "Wojciech", "start": 30, "end": 38,
                "role": "staff", "reason": "a driver called"}]}
   ```

   `role` is one of the config's `[cues]` roles or "other"; `decision` is redact, keep or
   unsure. The model never returns rewritten text.
4. **Check the model in code.** Reject any item whose quote is not exactly the text at its
   offsets in that turn. Apply only redactions; the rest of the text must be byte for byte
   the same. Merge as a union of local and model findings. A "keep" may overrule weak
   evidence (a first-name-list hit on a word), never a known-list match.
5. **Review queue.** Unsure items, disagreements between the rules and the model, fuzzy
   matches and word-names go to a person, with the flags `Result.flags` already gives.

Test it on made-up transcripts first. Write 60 or more with someone who has not seen the
rules: agent and customer talking, colleagues, family members and third parties named, by
full name, first name, nickname, initial, misheard spelling, and names that are words. Mark
every name with its role, in the bench's JSON shape. Keep a third unseen. Then, inside the
approved environment only, two people annotate 150 to 300 real transcripts. Report recall
per name mention by type, the share of calls leaking any name, over-redaction and cost. If
300 mentions show no misses, the miss rate is under 1% at 95% confidence (the rule of three,
3/n).

## First steps

1. Run the tests and the four bench runs, and confirm the figures above.
2. Ask the person you work for what the text is, where it lives, its format (speaker
   labels, timestamps), which metadata names the people in it, and which AI routes are
   approved.
3. Write a config for it, starting from the closest example.
4. Write a made-up test set with someone who has not seen your rules, and keep a third of it
   unseen.
5. Measure the config on that set, then build what the measurement says is missing.
6. Add a model pass only on an approved route, and measure it on the same set.
7. Put the flag queue in front of a person before anything is stored or shared.
