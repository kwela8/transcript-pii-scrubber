# pupil-name-scrubber

pupil-name-scrubber removes pupils' names and other personal data from school text:
support tickets, emails, chat, exports and logs. The Python package is called `hush`. It
uses the standard library only, makes no network or model call, and writes nothing to disk
unless you ask for an output file. Version 0.1.0.

It has a general identifier core and a layer for school text on top: the class list, a
first-name list from the ONS, logins, UPNs and ULNs, and five presets for the jobs a school
or an education technology company has. `docs/explainer.html` covers the same ground on one
page, with figures.

## Try it

From the repository root (tested on Python 3.14; nothing outside the standard library):

```
python3 -m hush presets
python3 -m hush scrub --roster examples/class-9X.csv examples/ticket.txt
python3 -m hush table examples/export.csv /tmp/export.out.csv
```

The second command turns lines like these:

```
Aisha hasn't logged in since Monday, so I reset her password (username akhan23,
UPN K801200345017). grace okafor said the Mark Scheme for task 3 was wrong.
Will is off sick this week. Will you check whether his Compulsory homework still shows?
```

into these:

```
[student 1] hasn't logged in since Monday, so I reset her password (username [username 1],
UPN [UPN 1]). [student 2] said the Mark Scheme for task 3 was wrong.
[student 3] is off sick this week. Will you check whether his Compulsory homework still shows?
```

"Will is off sick" loses Will, who is on the class list. "Will you check" keeps the verb.
"Mark Scheme" stays.

## Five presets

| preset | a found value becomes | use it for |
|---|---|---|
| `ask-ai` | a token, put back in the answer | sending a ticket, email or note to an AI model and reading its answer with the real names back |
| `share` | `[student 1]`, `[staff 2]`, `[email 1]` | Slack, Jira, slides, case studies, bug reports |
| `dataset` | `Pupil-3F9A1C`, the same in every file with the same key | exports for an analyst or researcher |
| `demo` | a made-up name of the same sex, made-up emails and phones | training material, demos, test fixtures |
| `logs` | labels, with no capitalised-name guess | logs and error reports sent to an outside tool |

`share` and `logs` refuse (print nothing, exit code 3) when the independent second check
still finds an identifier after scrubbing. `dataset` and `demo` warn instead.

## How it finds a pupil

The steps run in this order, and each one only looks at what the steps before it left.

1. **Emails and links, whole.** A name inside an address never splits it.
2. **Titled names.** "Mrs Pemberton" keeps "Mrs" and loses the name.
3. **Logins, UPNs and ULNs** by their shape, and the class list's own logins.
4. **The class list.** Every pupil's full name in any order ("Khan, Aisha"), any case,
   first, preferred and last names alone, possessives, and accents folded ("Zoe" finds
   "Zoë"). A table pasted into the text that has a Forename or Surname column adds its rows
   to the class list for that text.
5. **Names that are also words** ("Grace", "Will", "Summer", "Hope") need care. They are
   taken with a capital and in a name's place: not after "the", not before "Scheme" or
   "Term", and at the start of a sentence only before something a person does ("Will is",
   "Mason finds"). In lower case they are taken only before a verb: "grace hasn't logged
   in".
6. **The first-name list**: 22,643 names from the ONS baby names for England and Wales,
   1996 to 2025, any name given to 10 or more babies. Taken with a capital anywhere,
   including the start of a sentence. Not after "in" or "from" ("in Jordan").
7. **Screenshot misreads** of class-list names: one letter wrong, or 0, 1 and 5 for o, l
   and s ("Zlelinski", "Carva1ho").
8. **The core's identifier rules**: NHS number, National Insurance number, bank details,
   cards, phones, postcodes, addresses, every full date, every long number, every code that
   mixes letters and digits, labelled passwords and keys.
9. **The core's guess** at capitalised names from their neighbours, for anyone left. The
   guess only stands when a word in it is not an English word ("Oyelaran"), or it opens
   with a common name that is also a word ("Grace Baker", "for Grant"; not "Hope Street" or
   "Will you"), or it sits next to a name already taken.

Then a **second check**, written separately, reads the result and refuses it if an
identifier shape is still there.

## From Python

```python
from hush import Hush, read_roster

roster = read_roster("class-9X.csv")             # Forename, Surname, Preferred, Username, UPN
h = Hush("ask-ai", roster=roster)
result = h.scrub(ticket_text)
if result.refused:
    raise SystemExit("not sent: " + str(result.findings))
reply = call_your_model(result.text)              # the model only sees tokens
print(result.restore(reply))                      # real names back in the answer
```

`result.removed` counts what went, by kind. It never holds a value.

For exports, `hush.tables.scrub_csv(text, "dataset", key=key)` replaces the name columns,
keeps only the year of a date of birth and the outward part of a postcode, leaves numbers
and dates alone, and scrubs every other text column with the export's own names as the
class list.

## The class list

A CSV with a header row. hush finds the columns by name: `Forename` or `First name`,
`Surname` or `Last name`, or a single `Name` ("Aisha Khan" or "Khan, Aisha"), and any of
`Preferred`, `Username`, `Email`, `UPN`, `ULN`. Pass the school's whole roll if you can.
`--staff` takes a staff list the same way. `examples/class-9X.csv` shows the shape.

## Keys

`dataset` and `demo` use a key so the same pupil gets the same code in every run. Keep it
in an environment variable or a secret store and pass its name: `--key-env HUSH_KEY`. With
the key anyone can test a guess ("is Pupil-3F9A1C Aisha Khan?"), so treat it like a
password. Without a key, codes are stable within one run only.

## Tests and the bench

```
python3 -m unittest discover -s tests
python3 bench/student_bench.py bench/student_cases.json
python3 bench/student_bench.py bench/student_cases_2.json
python3 bench/student_bench.py bench/student_cases_3.json
```

The bench prints recall by kind for six configurations, from the core alone up to the
`share` and `logs` presets, in about 8 seconds a set. Point it at your own cases in the
same JSON shape to measure on text like yours.

The two pages in `docs/` are built by the scripts in `tools/docs/`, run from the repository
root:

```
python3 tools/docs/preset_demo.py > preset_demo.json
python3 tools/docs/build_explainer.py docs/explainer.html preset_demo.json
python3 tools/docs/build_plan.py docs/explainer.html docs/transcripts-plan.html
```

The bench figures in the explainer are typed in, so update them when the bench changes.

## Measured figures

The three test sets are synthetic. Each was written by a separate AI tester that never saw
the code: support notes, teacher and parent emails, chat, Slack, CSV, TSV and JSON exports,
logs, report comments, SEN notes and screenshot text. Each case comes with the class list a
school would hold and every piece of personal data marked. Sets 1 and 2 were used to tune
the rules, so their figures flatter the tool. Set 3 was the held-out set.

- **Set 1**: 150 cases, 784 pupil-name sightings, 40 texts with no names in them.
- **Set 2**: 80 cases, 356 sightings, 30 texts with no names. With the core alone, the
  guess took Title Case school words ("Simultaneous Equations", "Access Arrangements",
  "Rose Lane") in 22 of its 30 name-free texts. The guess filter in step 9 came from that.
- **Set 3**: 60 cases, 221 sightings, 25 texts with no names. Held out.

Pupil names caught, as a share of every sighting:

| | core alone | + first-name list | + class list | `share` preset |
|---|---|---|---|---|
| set 1 (tuned on) | 64.7% | 87.5% | 96.9% | 97.7% |
| set 2 (tuned on) | 68.0% | 81.7% | 90.4% | 92.4% |
| **set 3 (held out)** | **70.6%** | **80.5%** | **90.5%** | **90.5%** |

Set 3 in more detail, `share` preset against the core alone:

| | core alone | `share` |
|---|---|---|
| pupils on the class list (138 sightings) | 69.6% | 97.1% |
| nicknames, initials, misreads of class-list pupils (45) | 51.1% | 62.2% |
| pupils not on the class list (38) | 97.4% | 100% |
| adults (97) | 92.8% | 95.9% |
| logins (35) | 42.9% | 88.6% |
| email, phone, UPN, ULN, date of birth, postcode (112) | 90.9 to 100% | 96.3 to 100% |
| texts with no names that still lost a word (of 25) | 22 | 3 |
| texts restored exactly from tokens (of 60) | 60 | 58 |

Notes on the scoring:

- A sighting counts as caught when no letter or digit of it is left in place. A title
  kept in front of a name ("Mrs [person 1]") is not counted as a leak.
- The two inexact restores are the same person written in two casings ("taylor reid",
  "Taylor Reid"). Both get one token, so the model sees one person, and both come back in
  the first casing seen.
- One fault that set 3 showed was fixed after its first run: the first-name list took
  "jordan" out of "@jordan.p" before the handle rule could see the whole handle. The
  logins figure on set 3 therefore counts as in-sample.
- 38 off-list pupils is a small sample. Set 2's 92 gave 94.6%.

## What it misses

- Nicknames and initials of class-list pupils: "Alex P.", "Kiran S.", "TJ", "Mo". About
  six in ten are caught. Add known nicknames to the class list's Preferred column.
- A pupil's name in lower case when the name is also a word and nothing after it marks a
  person: "ruby", "faith", "storm" in quick chat.
- Names badly misread from a screenshot ("Wel Chen" for Wei Chen, "Bi11" for Bill).
- Rare names that are also words, alone mid-sentence ("Ash", "Moss"): the guess only
  takes a word-name given to 1,000 babies or more.
- Logins with no dot, digit or label ("whopkins", "browlands").
- Addresses: 4 of 10 on set 3. A street name that is also a first name can split the
  address rule.
- Pupils not on the class list whose names are not on the ONS list and who appear only
  at the start of a sentence before a word other than "has", "is", "was" and the like.
- It takes some words that are not people: towns ("Bradford", "in Leeds, Bradford and
  Sheffield"), places that are also first names (Paris, Jordan, India), street names, and
  a JSON field called "name" whatever it holds.
- Organisations and school names are not removed.
- Free text that identifies without a name ("the only Year 9 with a cochlear implant")
  is not touched. No pattern tool can see that.

## Before using it on real text

1. Always pass the school's roll. It is the single largest gain.
2. Where a pupil table is available, build the first-name list from it (every distinct
   first name with a count) instead of the ONS file. `tools/build_names.py` shows the
   shape.
3. Measure on real text before trusting the figures above: a few hundred real tickets,
   scrubbed, read by someone the data protection officer trusts, and scored with the bench.
4. Keep the second check on for anything that leaves your own systems.

## Call transcripts

`docs/transcripts-plan.html` sets out an extension for customer call transcripts between a
support coach and school staff: remove every name that is not a known speaker's, flag the
likely pupils for a person to review, and use a language model only to judge candidates
that the rules have already found. It includes the research behind the design and its
sources. `AGENTS.md` turns the plan into a specification for an AI coding agent working in
this repository. The extension is not built yet.

## Sources and licence

- `hush/lists/first_names.txt`, `name_words.txt`, `common_first_names.txt`, `name_sex.txt`:
  derived from "Baby names in England and Wales: 1996 to 2025", Office for National
  Statistics, under the Open Government Licence v3.0.
- `hush/lists/words.txt` and the name-word split: from the SCOWL word lists (Debian
  `wbritish`), copyright Kevin Atkinson and others; see NOTICE and
  `licences/SCOWL-copyright.txt`.
- The code: MIT licence, by Pierre Sutherland, see LICENSE.
