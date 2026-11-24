# Transcript PII scrubber

Transcript PII scrubber checks a transcript, or any other text, for the kinds of personal
data you choose, and replaces them before the text goes to an AI model, a chat, a ticket, a
dataset or a log. The Python package is called `hush`. It uses the standard library only,
makes no network or model call, and writes nothing to disk unless you ask for an output
file. Version 0.2.0.

What it looks for, and what it leaves alone, is set by a config file: which detector packs
run, who the known people are, which names to keep, which words are never a name, your own
patterns, and which kinds are only flagged for a person to review. Three worked examples
are in `examples/`: support calls, a document before an AI model reads it, and school text.
`docs/explainer.html` covers the same ground on one page, with figures. How it compares with
Presidio and GLiNER on five public test sets is below.

## Try it

From the repository root (tested on Python 3.14; nothing outside the standard library):

```
python3 -m hush presets
python3 -m hush packs
python3 -m hush scrub --config examples/support-call/hush.toml examples/support-call/call.txt
python3 -m hush scrub --config examples/llm-document/hush.toml examples/llm-document/notes.txt
python3 -m hush scrub examples/llm-document/notes.txt
```

The third command turns a call like this:

```
[00:00:12] Priya Shah: No problem, Gareth. Could you confirm the account reference and your date of birth?
[00:00:18] Gareth Lyle: It's GL4471902, and I was born on 14/09/1961.
[00:00:30] Gareth Lyle: It arrived dented. My son Callum Lyle took it back to the depot and a driver called Wojciech said it would be refunded, but nothing has come through.
[00:00:41] Priya Shah: I'm sorry about that. I'll raise it with my manager, Dervla Quinn, today. Is 07700 900481 still the best number?
```

into this:

```
[00:00:12] Priya Shah: No problem, Gareth. Could you confirm the account reference and your date of birth?
[00:00:18] Gareth Lyle: It's [account 1], and I was born on [date of birth 1].
[00:00:30] Gareth Lyle: It arrived dented. My son [family 1] took it back to the depot and a driver called [staff 1] said it would be refunded, but nothing has come through.
[00:00:41] Priya Shah: I'm sorry about that. I'll raise it with my manager, [staff 2], today. Is [phone 1] still the best number?
```

The agent and the customer stay: the agent is on the config's keep list, and the customer
is a speaker the transcript names. Everyone else goes. A removed name with a family or work
word near it ("my son", "my manager") is labelled by that role and flagged for review, and
standard error lists the flags by kind, never the values.

## Five presets

| preset | a found value becomes | use it for |
|---|---|---|
| `ask-ai` | a token, put back in the answer | sending a transcript, ticket, email or note to an AI model and reading its answer with the real values back |
| `share` | `[person 1]`, `[customer 2]`, `[email 1]` | chats, tickets, slides, case studies, bug reports |
| `dataset` | `Person-3F9A1C`, the same in every file with the same key | exports for an analyst or researcher |
| `demo` | a made-up name of the same sex, made-up emails and phones | training material, demos, test fixtures |
| `logs` | labels, with no capitalised-name guess | logs and error reports sent to an outside tool |

`ask-ai`, `share` and `logs` refuse (print nothing, exit code 3) when the independent second
check still finds an identifier after scrubbing. `dataset` and `demo` warn instead.

## Detector packs

| pack | on by default | finds |
|---|---|---|
| `general` | yes | emails, links, IP addresses, cards (Luhn), IBANs, international phones with extensions, street addresses with flat, town, state, postal code and country, PO boxes, full dates with a weekday or time, dates with no year, long numbers, codes that mix letters and digits, labelled passwords, keys and PINs, usernames and handles, labelled passports, licences, plates, dates of birth and addresses, a name, phone or plate after a cue ("my name is", "call me on"), JSON fields, numbers read out as words |
| `uk` | yes | NHS numbers (mod 11), National Insurance numbers, sort codes and account numbers, UK phones, postcodes, house-number addresses, vehicle registrations and driving licences |
| `north-america` | yes | North American phone numbers, a town with its state and ZIP code, Canadian postal codes |
| `south-africa` | no | South African ID numbers after their label, Afrikaans and Dutch street names |

The second check reads for the same packs the scrub ran. A rule for another country goes in
its own pack in `hush/core.py` (`_Rule(..., pack="name")`, and a line in `PACKS`), or in a
config as your own detector.

## How it finds a name

The steps run in this order, and each one only looks at what the steps before it left.

1. **Emails and links, whole.** A name inside an address never splits it. In a pasted
   table, the cells under a password or key column go too.
2. **Names to keep**: the config's keep list and the speakers it keeps, in every form
   ("Priya Shah", "Shah, Priya", "Priya", "Ms Shah"). A kept first name before another
   surname ("Priya Okonjo") is someone else and is not kept.
3. **Names and IDs**, found together; where two overlap, the longer wins.
   - **Titled names.** "Mrs Pemberton" keeps "Mrs" and loses the name.
   - **Your own detectors** from the config, and the known people's IDs, usernames and
     emails.
   - **Logins and handles** by their shape and their labels.
   - **The known people.** Each person's full name in any order ("Lyle, Gareth"), any
     case, first, preferred and last names alone, possessives, and accents folded ("Zoe"
     finds "Zoë"). A table pasted into the text with a First name, Surname or Name column
     adds its rows for that text.
   - **Names that are also words** ("Grace", "Will", "Summer", "Hope") need care. They are
     taken with a capital and in a name's place, and in lower case only before a verb:
     "grace hasn't logged in".
   - **The first-name list**: 22,643 names from the ONS baby names for England and Wales,
     1996 to 2025, any name given to 10 or more babies. Taken with a capital anywhere, and
     in lower case when the preset asks (`share`, `logs`), with the next lower-case word
     when it is not an English word ("daniel okafor"). Not after "in" or "from" ("in
     Jordan").
   - **Screenshot misreads** of known names: one letter wrong, or 0, 1 and 5 for o, l and s.
4. **Numbers read out as words** ("oh seven seven double oh nine hundred"), then **the
   packs' identifier rules**, then every long number.
5. **A guess** at capitalised names from their neighbours, for anyone left. The guess only
   stands when a word in it is not an English word ("Oyelaran"), or it opens with a common
   name that is also a word ("Grace Baker", "for Grant"; not "Hope Street" or "Will you"),
   or it sits next to a name already taken.

Then a **second check**, written separately, reads the result and refuses it if an
identifier shape is still there.

## The config file

TOML (read with the standard library) or JSON with the same keys. Every key is optional,
and paths are read from the config's own folder. `hush/config.py` lists every key; this is
`examples/support-call/hush.toml`, cut down:

```toml
name = "support-call"
preset = "share"
flag = ["DATE"]                  # left in place and listed for review

[packs]
general = true
uk = true
north-america = true

[people]
keep = ["agents.txt"]            # one name per line, or a CSV
# known = ["customers.csv"]      # people to remove in all their forms
# role = "customer"              # their label when a row names no role

[words]
keep = ["Ellis", "Harper Plus"]  # product names that look like names

[transcript]
speakers = "keep"                # text, keep or relabel

[[detectors]]
kind = "ACCOUNT_REF"
label = "account"
pattern = '\b[A-Z]{2}\d{7}\b'

[cues]
family = ["son", "daughter", "wife", "husband", "mum", "dad"]
staff = ["manager", "colleague", "engineer", "driver"]
```

Also available: `check` (refuse, warn or off), `[names]` (`list`, `any_case`, `guess`,
`files` with more first names), `[people] columns` (your CSV's headers), `login_labels`,
`[words] keep_files`, `[[redact]]` (words and phrases always removed, with a kind and a
label), `[transcript] roles` (a role per speaker for `relabel`), `[cues] window` (words
either side, default 4), `[labels]` (what a kind is called in a label), `[dates] years`
(`off` by default; `near` takes a year after a word that dates it, "born in 1985", and `all`
takes every year 1900 to 2099, as kind YEAR, which `flag` can leave in place instead) and
`[warn] quasi` (how many ages, places, jobs, dates and rare details left in one text earn a
warning, default 5, 0 for none; `Result.quasi` and `Result.warnings`, and standard error on
the command line; nothing is removed for them). A mistake in the file stops the run with a
message naming the key.

## Known people and names to keep

A known-people file is a CSV with a header row: `First` (or `Forename`) and `Last` (or
`Surname`), or a single `Name` ("Gareth Lyle" or "Lyle, Gareth"), and any of `Preferred`,
`Username`, `Email`, `ID` and `Role`. `Preferred`, `Username`, `Email` and `ID` may hold
several values split by `;`. A plain text file with one name per line works too. A known
person is labelled by role: `[customer 1]` when the row or the config says customer, else
`[person 1]`.

A keep file has the same shape. A kept person is never removed, in any form, and keeping a
person who is also on the known list keeps their preferred names from it too.

## Transcripts

`hush/transcripts.py` reads speaker labels at the start of each turn: `Agent:`,
`Speaker 1:`, `SPEAKER_01:`, `[00:01:02] Priya:`, `00:01:02 Priya Shah:`,
`PRIYA (10:02):`, `Priya Shah [00:01:02]:` and WebVTT `<v Priya Shah>`. A label that names a
role ("Agent", "Customer", "Speaker 2") stays as it is. Headings such as `Subject:` and
`Note:` are not speakers. A one-word label takes the fuller name the transcript gives once
("DANIEL" and "it's Daniel Okafor").

`[transcript] speakers` decides what happens to a speaker who is a person:

- `text`: the label is ordinary text, and the name rules apply to it.
- `keep`: the speaker is kept, in the label and wherever the transcript names them.
- `relabel`: the speaker becomes one placeholder all the way down, in the label and in the
  text, with the role `[transcript] roles` gives that label ("[agent 1]:") or "speaker".

Lower-case speech-to-text works with the `share` and `logs` presets, which take
first-name-list names in any case, and the core reads out numbers said as words.

## From Python

```python
from hush import Hush, Person

h = Hush("ask-ai", config="examples/support-call/hush.toml")
customer = Person("Gareth", "Lyle", role="customer")
result = h.scrub(call_text, keep=[customer])     # per call, from the call record
if result.refused:
    raise SystemExit("not sent: " + str(result.findings))
reply = call_your_model(result.text)              # the model only sees tokens
print(result.restore(reply))                      # real values back in the answer
```

`result.removed` counts what went, by kind, and `result.flags` lists what to review (kind,
where it sits in `result.text`, why). Neither holds a removed value.

For exports, `hush.tables.scrub_csv(text, "dataset", config=..., key=key)` replaces the
name, contact and ID columns, keeps only the year of a date of birth and the outward part of
a postcode, leaves numbers and dates alone, and scrubs every other text column with the
export's own names as known people.

## Customise it

1. Copy the example config closest to your text.
2. Turn off the packs for countries your text never mentions, and turn on any it does.
3. Put your own staff, agents or authors in a keep file, and the people your text is about
   (customers, patients, members) in a known-people file. The known list is the single
   largest gain in every measurement below.
4. Add your product, team and place names that look like names to `[words] keep`, your own
   reference numbers as `[[detectors]]`, and client names that must never leave as
   `[[redact]]`.
5. For another country's first names, add a file of names (one per line) under
   `[names] files`, or rebuild the lists from that country's register with
   `tools/build_names.py`, which shows the shape. The built-in list is from births in
   England and Wales, so names common elsewhere and rare there are missed by it.
6. Write 40 or more made-up texts like yours, mark every value in the bench's JSON shape,
   and run the bench with your config.

## Keys

`dataset` and `demo` use a key so the same person gets the same code in every run. Keep it
in an environment variable or a secret store and pass its name: `--key-env HUSH_KEY`, or
`key_env = "HUSH_KEY"` in the config. With the key anyone can test a guess ("is
Person-3F9A1C Gareth Lyle?"), so treat it like a password. Without a key, codes are stable
within one run only.

## Tests and the bench

```
python3 -m unittest discover -s tests
python3 bench/bench.py bench/general/cases.json
python3 bench/bench.py bench/general/cases.json --config examples/support-call/hush.toml
python3 bench/bench.py bench/education/cases_3.json --config examples/education/hush.toml
```

There are 124 tests. The bench takes any test set in its JSON shape (described at the top
of `bench/bench.py`) and any config, and prints recall by kind for six columns, from the
patterns alone up to the config's preset and `logs`, in a few seconds a set.

`bench/public/` runs hush, Presidio and GLiNER over the five public sets below with one
scorer. Its README says where to download each set, under which licence, and the commands.
No data is in the repository.

The two pages in `docs/` are built by the scripts in `tools/docs/`, run from the repository
root:

```
python3 tools/docs/preset_demo.py > preset_demo.json
python3 tools/docs/build_explainer.py docs/explainer.html preset_demo.json
python3 tools/docs/build_plan.py docs/explainer.html docs/transcripts-plan.html
```

The bench figures in the explainer are typed in, so update them when the bench changes.

## How it compares

Five openly licensed PII test sets, scored the same way for every tool: a marked span
counts as removed when none of its letters or digits is left. hush ran with no config,
Presidio with its defaults and spaCy's `en_core_web_lg`, GLiNER as
`knowledgator/gliner-pii-large-v1.0` with 30 labels at a threshold of 0.3. The `share`
preset, all marked spans:

| set | hush 0.1.0 | hush now | Presidio | GLiNER |
|---|---:|---:|---:|---:|
| PII-TRACE, 500 dialogues (held out) | 82.5% | 94.3% | 62.3% | 53.0% |
| Nemotron-PII, 1,000 documents (tuned on) | 69.0% | 76.1% | 63.5% | 60.6% |
| Nemotron-PII transcripts, 196 (tuned on) | 70.2% | 76.0% | 66.1% | 58.9% |
| Synthetic chat lines, 500 (tuned on) | 86.2% | 97.2% | 65.2% | 96.0% |
| TAB, 127 court cases (held out) | 61.8% | 68.1% | 72.6% | 57.5% |

hush now, against the two others (hush / Presidio / GLiNER):

| set | names | span precision | words wrongly removed per 1,000 | documents with a name left |
|---|---|---|---|---|
| PII-TRACE | 100 / 78.7 / 77.1% | 96.5 / 95.2 / 77.9% | 0.7 / 1.8 / 5.8 | 0 / 99 / 118 of 218 |
| Nemotron-PII | 96.4 / 87.6 / 85.4% | 89.1 / 87.9 / 98.6% | 9.7 / 12.7 / 1.1 | 38 / 107 / 93 of 482 |
| transcripts | 98.7 / 82.4 / 77.9% | 93.9 / 85.3 / 99.2% | 6.2 / 11.8 / 0.9 | 12 / 56 / 113 of 184 |
| chat lines | 93.3 / 86.3 / 96.2% | 100 / 94.8 / 100% | 0.0 / 8.7 / 0.0 | 30 / 61 / 17 of 365 |
| TAB | 89.5 / 87.0 / 66.0% | 90.3 / 86.6 / 84.8% | 5.8 / 15.4 / 9.9 | 37 / 41 / 47 of 127 |

On PII-TRACE's 50 dialogues with no personal data, hush touched 30 (2.9 words per 1,000),
Presidio 18 and GLiNER 22. On TAB, Presidio removes more addresses (79.9% against 35.9%)
and dates (98.9% against 79.7%); hush removes more application and case numbers (94.0%
against 5.6%).

Read these with care:

- All five sets are synthetic or legal text, not real call transcripts: no lower-case
  speech-to-text names, fillers or misheard words. Real transcripts will be harder for every
  tool, and hardest for hush's capitalised-name guess.
- PII-TRACE's names are invented words, which suits hush's "not an English word" rule and
  flatters its name score. The Nemotron sets use realistic names.
- hush was tuned on the Nemotron sets and the chat lines, reading their misses. PII-TRACE
  and TAB were held out: none of their misses were read. But their weak categories were
  known from the first run (PII-TRACE addresses at 0% and phones at 38%, TAB's years), so
  the address, phone and date rules were written knowing what those sets lacked.
- Presidio ran with its default settings; neither it nor GLiNER was tuned. GLiNER moved a
  lot with its label list: with 10 plain labels in place of 30 it removed 84.1% on
  PII-TRACE (98.2% of addresses) but 47.3% on the Nemotron sample, and on the chat lines
  it left a name in 1 document of 365 where hush left one in 30.
- hush 0.1.0 is commit eb88b03. The general version before this work (c11f5df) scored the
  same as 0.1.0 except Nemotron-PII 70.3%, transcripts 71.1% and TAB 62.3%.

## Measured figures

All test text is synthetic. Each set was written by a separate AI tester that never saw the
code, with every piece of personal data marked.

**The general set** (`bench/general/cases.json`): 41 texts and 12 with no personal data:
support calls (four of them lower-case speech-to-text), meeting notes, CVs, complaint
emails, chat logs, a letter, an HR note, a form, a report, an app log, a CSV, a JSON record
and a helpdesk ticket. 322 name sightings, 89 sightings of names to keep, 196 of other
identifiers.
With no config:

| | patterns only | + first-name list | + known people | `share` preset |
|---|---|---|---|---|
| names, all (322) | 73.6% | 80.7% | 86.0% | 88.8% |
| on the known list (97) | 71.1% | 82.5% | 99.0% | 99.0% |
| known people written another way: nicknames, initials, reordered (32) | 50.0% | 50.0% | 53.1% | 62.5% |
| not on the known list (193) | 78.8% | 85.0% | 85.0% | 88.1% |
| kept names left whole (89) | 94.4% | 93.3% | 100% | 100% |
| texts with no personal data that lost a word (of 12) | 8 | 3 | 3 | 3 |

Phones, emails, postcodes, dates of birth, cards, bank details, IP addresses and NI
numbers: 100% in every column. Usernames 93.5%, reference numbers 89.7%, secrets 4 of 5,
addresses 78.6%. The "+ first-name list" column does not load a case's names to keep, so a
member of staff who says "my name is ..." goes there. 39 of 41 texts restore exactly with
`ask-ai`; the other two hold one name in two cases of letter ("Shabnam", "shabnam"), which
comes back in the first case seen.

The general set is not a clean held-out set. Its first run showed two faults that were then
fixed: a kept person on the known list lost their nickname to it (kept names 91.0% before,
100% after), and a titled name with a letter outside Latin-1 ("Mr Szymański") was cut in
two. Names overall went from 88.2% to 88.5%; the public-benchmark work then took them to
88.8% and addresses from 57.1% to 78.6%, without reading this set's misses.

**The education example** keeps hush 0.1.0's figures, or betters them, on the three school
sets it was built on (`bench/education/`), with `examples/education/hush.toml`. On the
held-out set 3: pupil names 91.0% (90.5% in 0.1.0), pupils on the class list 97.8% (97.1%),
nicknames and initials 62.2%, adults 95.9%, 3 of 25 name-free texts touched, 58 of 60 exact
restores. `examples/education/README.md` has the detail.

## What it misses

- Nicknames and initials of known people ("Kev" for Kevin, "JK"): about six in ten are
  caught. Put known nicknames in the Preferred column.
- Names that are also words, mid-sentence with a capital ("Mark", "Hope", "Bill", "Frank")
  or in lower case with nothing after them that marks a person ("jade").
- Lower-case surnames that are also words ("daniel smith") unless the person is known, and
  lower-case titled names ("mrs obrien").
- Names in capitals in forms ("MARIANA COSTA FERREIRA").
- Addresses: 78.6% on the general set, 35.9% on TAB. A town or a country on its own, with
  no street before it and no state and ZIP code after it, stays.
- A year on its own ("in 2019") stays unless `[dates] years` asks for it.
- Logins made of names run together in lower case ("jbenoit"): a word list cannot tell them
  from ordinary words it lacks, so they stay unless a label says "username".
- Organisation names. They stay, and a company named like a person ("Brightwater
  Broadband", "Taylor Wimpey") may be taken as one.
- It takes some words that are not people: towns, places that are also first names (Paris,
  Jordan, India), and a greeting the first-name list holds ("Hiya").
- Free text that identifies without a name ("the only engineer on the night shift") is not
  removed. hush counts ages, places, jobs, dates and rare details left in a text and warns
  above a threshold (`[warn] quasi`), but the count is a prompt to read again, not a measure.

## Before using it on real text

1. Pass the known people and the names to keep. They are the largest gain.
2. Measure on real text before trusting the figures above: a few hundred real texts,
   scrubbed, read by someone your data protection lead trusts, and scored with the bench.
3. Keep the second check on for anything that leaves your own systems.

## Changes from 0.1.0

hush 0.1.0 was built for school text. 0.2.0 makes the school parts one example among others.

- `hush.students` is now `hush.people`; `Pupils` is `People` (`known`, `keep` and the
  config's settings), `Person` has `id` and `role` in place of `upn`, `uln` and `kind`,
  and `Pupils.known` is `People.names_on_list`. `read_roster` is still there, as
  `read_people`.
- `Hush(preset, roster=...)` still works; `people=`, `keep=` and `config=` are new, and
  `Hush.scrub(text, people=..., keep=...)` adds people for one text.
- UPN and ULN rules, school column names, the `pupil`, `student` and `learner` login labels
  and the school vocabulary left the core for `examples/education/`. Known people's kinds
  are `PERSON_<ROLE>`: STUDENT is now PERSON_STUDENT, STAFF is PERSON_STAFF.
- Pseudonyms start with the role's label: `Person-`, or `Student-` in the education example,
  where 0.1.0 wrote `Pupil-`. The code after the dash is unchanged.
- `core.scrub(profile=...)` still works and `packs=` is new. A labelled home address needs
  its colon in every pack; South African ID numbers and Afrikaans street names are a pack
  that is off by default. `core.scrub(students=...)` is `people=` (the old name still
  works).
- Fixes: the first made-up name in a `demo` run could take the wrong sex; a titled name
  with a letter outside Latin-1 ("Mr Szymański") was cut in two.
- The bench is `bench/bench.py`, for any test set and config; the school sets moved to
  `bench/education/`.
- `Result.flags` is new; the CLI has `--config`, `--people` (`--roster` still works),
  `--keep` and `packs`.

Since the first public benchmark (all with tests, and the education figures checked):

- Titled names with any Latin letter, "O'Brien", "McDonald" and "van der Berg" go whole.
- Phones: extensions, North American and bracketed area-code shapes, numbers read out
  with "um" and "er" between the digits.
- Street addresses with flat, town, state, postal code and country, street word first or
  last, PO boxes, labelled ZIP codes; in `north-america`, a town with state and ZIP and
  Canadian postcodes. Addresses are found before names, so a street named like a person
  goes whole.
- Dates with a weekday or a time, dates with no year, a month and year; `[dates] years`.
- Usernames after more labels ("the user name was ...", Markdown labels) and in login
  shapes built from names ("Samuel1995", "Nimali.Sivagnanam", "k.williams").
- Every other mention of a found name, in any case, possessives included.
- A name, phone or plate after a cue ("my name is", "call me on", "licence plate").
- Restore puts back a token a model changed in case, spacing or brackets
  (`Restored.variants`) and refuses, and counts, one that was never issued.
- `Result.quasi`, `Result.warnings` and `[warn] quasi`; `hush/quasi.py`.

## Sources and licence

- `hush/lists/first_names.txt`, `name_words.txt`, `common_first_names.txt`, `name_sex.txt`:
  derived from "Baby names in England and Wales: 1996 to 2025", Office for National
  Statistics, under the Open Government Licence v3.0.
- `hush/lists/words.txt` and the name-word split: from the SCOWL word lists (Debian
  `wbritish`), copyright Kevin Atkinson and others; see NOTICE and
  `licences/SCOWL-copyright.txt`.
- The code: MIT licence, by Pierre Sutherland, see LICENSE.
