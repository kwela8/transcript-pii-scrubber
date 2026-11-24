# AGENTS.md

Guidance for an AI coding agent working in this repository. Read this file, then
`docs/explainer.html` and `docs/transcripts-plan.html`, before you change anything.

The repository holds a working, measured tool: the Python package `hush` (version 0.1.0,
standard library only, MIT licence). It removes pupils' names and other personal data from
school text. The next piece of work it is set up for is an extension to customer call
transcripts, specified below and in `docs/transcripts-plan.html`. You are extending a
measured design, not inventing one.

## What is here

| Path | What it is |
|---|---|
| `hush/core.py` | Tokens and restore, the identifier rules, the protected vocabulary (`KEEP`) and the capitalised-name guess |
| `hush/students.py` | The pupil layer: class list, first-name list, name-words, logins, UPNs, ULNs, screenshot misreads, and the guess filter `keep_guess` |
| `hush/residual.py` | The second check, written apart from the detectors |
| `hush/presets.py` | The five presets, `Hush` and `Result` |
| `hush/styles.py` | What a found value becomes: token, label, pseudonym or fake |
| `hush/tables.py` | CSV exports, column by column |
| `hush/__main__.py` | The command line |
| `hush/lists/*.txt` | First names (ONS), name-words, common names with sex, English words (SCOWL) |
| `tools/build_names.py` | Rebuilds the lists from the ONS workbook and a word list |
| `bench/student_bench.py` | The pupil-name bench |
| `bench/student_cases*.json` | Three made-up test sets: 290 cases, 1,361 pupil-name sightings, 95 name-free texts |
| `examples/` | A class list, a support ticket and a CSV export, all made up |
| `tests/test_hush.py` | Unit tests |
| `docs/explainer.html` | What the tool does and how well, for people |
| `docs/transcripts-plan.html` | The design for call transcripts, with the research behind it |
| `NOTICE`, `licences/` | Where the lists come from and their licences |

Every name in the repository is made up.

## Commands

Run everything from the repository root.

```
python3 -m unittest discover -s tests
python3 bench/student_bench.py bench/student_cases.json
python3 bench/student_bench.py bench/student_cases_2.json
python3 bench/student_bench.py bench/student_cases_3.json
python3 -m hush scrub --roster examples/class-9X.csv examples/ticket.txt
```

Run the tests and all three bench sets before and after every change, and compare the
figures with the ones under "How to measure".

## Ground rules

1. Transcripts and tickets that mention pupils are personal data about children. Do not
   paste real ones into a chat, a test file or any outside API unless the data protection
   lead of the organisation that owns them has approved that route (a contract that rules
   out training, a UK or EU region, a retention limit). Build and test on the made-up sets
   first.
2. Logs, reports and errors carry counts only, never a removed value. `Result.removed`
   counts by kind and holds no value; keep it that way.
3. Keep a second check that is written separately from the detectors and reads only the
   output (`hush/residual.py`). If it still finds an identifier shape, the default is to
   refuse, not to warn.
4. Keep one test set unseen while you tune, and report the unseen figure as the real one.
   Set 3 is the held-out set. If you tune against it, write a new held-out set and say so.
5. A name the tool cannot place is flagged for a person to look at. It is never silently
   kept.
6. Standard library only, no network, and nothing written to disk unless the caller asks.

## The design in the code

### Tokens and restore

Each found value becomes a token `<P{16 hex}_{KIND}_{NNNN}_{16 hex check}>`
(`hush/core.py`, `TOKEN`). The first 16 hex digits are a per-run namespace, NNNN counts per
kind, and the check is an HMAC of the value under a per-run key, so a forged token is never
restored. The value-to-token map lives in memory only. Restore replaces only exact issued
tokens and counts anything token-shaped that was not issued. For name kinds (PERSON,
STUDENT, STAFF) the same person in any case gets one token, so a model sees one person
once; restore gives back the first casing seen.

### The order of rules

Each rule only looks at text outside the tokens already issued.

1. **Emails and links**, whole.
2. **Titled names.** `(Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Sir|Dame)\.? ` then one to three
   capitalised words or an initial and a surname, or the same in capitals. The title stays
   outside the token ("Mrs [person 1]").
3. **Identifiers by shape.** UPN: `(?<![A-Za-z0-9])[A-Z]\d{11}[0-9A-Z](?![A-Za-z0-9])`.
   ULN: `(?<![A-Za-z0-9.,])\d{10}(?![A-Za-z0-9]|[.,]\d)`. Handles: `(?<![\w@.])@` then the
   handle, except `@here`, `@channel` and `@everyone`. Chat speakers at the start of a
   line, with an optional `[time]`, shaped like a login (lower case with a dot or
   underscore, or letters then digits) before `: `. A value after a login label (`user`,
   `username`, `login`, `pupil`, `student`, `learner`, `uid`, then `:`, `=` or `is`) when it
   looks like a login. Login shapes that start with a name: `name.x`, `namek3`, `mo_khan`;
   a tail longer than three letters needs a head that is a known name, so `summer.term` and
   `max.value` stay.
4. **The class list.** Each pupil gives: the full name in either order (with a comma or a
   line break between), with possessives; preferred, first and last names alone in any
   case; usernames, emails, UPNs and ULNs. Accents and case are folded before comparing
   (NFKD, combining marks dropped, lower case). A two-letter name alone needs its capital.
   A table pasted into the text whose header has a Forename, Surname or Name column adds
   its rows to the class list for that text.
5. **Class-list names that are also English words** ("Grace", "Will", "Summer", "Mark")
   are taken with a capital only in a name's place: not after the, a, this, next, last,
   every, our, your, of, in, per, with and similar; not before Scheme, Term, Fair, Street,
   Road, Day, Week, Book, Time, House, Hall and similar place, event or thing words; at the
   start of a sentence only before a verb a person does (is, was, has, had, said, asked,
   joined, missed, forgot, logged, scored, struggled, wants, needs and their negatives). In
   lower case only before such a verb or as a possessive ("grace hasn't", "grace's").
6. **The first-name list** (`hush/lists/first_names.txt`, 22,643 names given to 10 or more
   babies in England and Wales, 1996 to 2025, that are not English words). Taken with a
   capital anywhere, and in lower case when the preset asks (`share` and `logs` do). Not
   straight after in, near, from, via, visit and similar ("in Jordan"). A capitalised
   surname of up to two words may follow, with particles (van, der, de, al, bin, ap, mc).
7. **A capitalised word that is not an English word** (`hush/lists/words.txt`) before a
   person verb: "Brathwaite has been late".
8. **Screenshot misreads** of class-list names of six letters or more: one edit away, or
   equal once 0, 1 and 5 read as o, l and s and "rn" as "m".
9. **The core identifier rules**: NHS number (mod 11), NI number, sort code and account,
   card (Luhn), UK phones, postcodes, house-number addresses, every full date, long
   numbers, codes mixing letters and digits, labelled passwords and API keys.
10. **The capitalised-name guess**: runs of capitalised words, except after a determiner,
    before a number ("Room 214"), alone in a table cell, at a sentence start when single,
    or made of protected words (`KEEP`: terms, roles, subjects, exam words, maths names
    such as Pythagoras and Pascal, and homework-platform words such as Method, XP and
    Boost). **The guess filter** (`keep_guess`) then lets a run stand only when one word in
    it is not an English word, or it opens with a word-name given to 1,000 babies or more
    (`hush/lists/common_first_names.txt`) followed by capitalised words that are not place
    or event words, or it is alone and not before you, this, the, to, by and similar ("for
    Grant" goes, "Will you" stays), or it sits straight after a name already taken.
    Without this filter the guess took a word in 22 of 25 name-free texts in set 3; with
    it, 3.
11. **The second check** reads the output only: emails, phones, NHS and NI numbers,
    postcodes, cards, long digit runs, handles, labelled secrets. Any hit refuses.

### Five presets

| Preset | Output | First-name list in any case | Guess | Second check |
|---|---|---|---|---|
| ask-ai | tokens, restored in the model's answer | no | on | refuse |
| share | `[student 1]`, `[staff 2]`, `[person 3]` | yes | on | refuse |
| dataset | `Pupil-3F9A1C` (HMAC of the person under a key) | no | on | warn |
| demo | made-up names of the same sex, `07700 900xxx` phones | no | on | warn |
| logs | labels | yes | off | refuse |

For CSV exports (`hush/tables.py`): name columns become the pupil's code, a date of birth
keeps its year, a postcode keeps its outward code, numbers stay, and every other text cell
is scrubbed with the export's own names as the class list.

## How to measure

Each test case is JSON: `id`, `shape`, `text`, `roster` (first, last, preferred), and
`spans` (value, kind, and for STUDENT `on_roster`: yes, variant or no). Negatives are texts
with no personal data. Scoring: a sighting is caught when none of its letters or digits is
left in place, aligning input and output with the tokens collapsed to one character; a
kept title is not a leak. The bench reports by kind, by class-list status and by shape,
with the negatives that lost a word and the exact restores.

Figures the current code gives, `share` preset:

| | set 1 (tuned on) | set 2 (tuned on) | set 3 (held out) |
|---|---|---|---|
| pupil names | 97.7% | 92.4% | 90.5% |
| pupils on the class list | 98.2% | 98.1% | 97.1% |
| nicknames, initials and misreads | 96.4% | 67.3% | 62.2% |
| adults | 99.3% | 90.1% | 95.9% |
| name-free texts that lost a word | 7 of 40 | 2 of 30 | 3 of 25 |
| exact restores | 150 of 150 | 79 of 80 | 58 of 60 |

A change that lowers any set 3 figure needs a reason in its commit message.

## Transcripts

The job: customer call transcripts between a support coach and school staff. Remove every
person's name that is not a known speaker's, and flag the ones that are likely pupils.
`docs/transcripts-plan.html` has the reasons and sources; this is the specification. None
of it is built yet. Build it on top of `hush` (for example a new module
`hush/transcripts.py`) rather than beside it, so it inherits the rules, the tokens and the
second check.

Inputs per call: the transcript with speaker labels and turn numbers; the names of the
known speakers (the coach and the member of school staff) from the call metadata; and the
school's ID, to fetch its class list if the data protection lead allows that use.

1. **Protect list.** Each known speaker's first name, surname, full name, title forms
   ("Mrs Patel", "Miss P"), initials, and spellings a transcriber might produce (one
   letter out). Protected names are never redacted or flagged.
2. **Local candidates.** Rules 1 to 10 above, with the school's class list as the roster
   and the first-name list in any case (transcripts are often lower case). Add fuzzy
   class-list matching up to two letters out for names of five letters or more. A local
   GLiNER model (Apache-2.0 only: the urchade, knowledgator or fastino PII models) with
   one label, "person", at a low threshold may add candidates; never let it remove one.
3. **Redact the sure ones locally**: exact class-list matches and every identifier. One
   stable placeholder per person across the whole call: `[PUPIL_1]`, `[STAFF_1]`,
   `[PARENT_1]`, `[PERSON_1]`.
4. **Model pass**, only on a route the data protection lead approved (the paid Gemini API
   or Vertex AI in London, `gemini-3.5-flash`, with logging and caching off). Send the
   partly scrubbed text in windows of about 40 turns overlapping by 5, with the speaker
   labels, the protect list and the numbered candidates still unresolved. Temperature 0.
   Five to ten worked examples in the prompt, including word-names ("Grace", "Will",
   "Summer"), nicknames, initials, a teacher who is not a speaker, and a maths name that
   must stay ("Pythagoras"). Require JSON against a schema:

   ```json
   {"candidates": [{"candidate_id": 3, "turn_id": 41, "quote": "jayden",
                    "start": 12, "end": 18, "role": "pupil",
                    "decision": "redact", "reason": "my son jayden"}],
    "missed": [{"turn_id": 44, "quote": "Kacper", "start": 30, "end": 36,
                "role": "pupil", "reason": "in Year 8"}]}
   ```

   `role` is pupil, staff, parent, provider or other; `decision` is redact, keep or
   unsure. The model never returns rewritten text.
5. **Check the model in code.** Reject any item whose quote is not exactly the text at its
   offsets in that turn. Apply only redactions; the rest of the text must be byte for byte
   the same. Merge as a union of local and model findings. A "keep" may overrule weak
   evidence (a first-name-list hit on a word), never a class-list match or a protected
   form check.
6. **Flags.** A removed name is flagged `likely_pupil` when it is on the class list, the
   model says pupil, or it is within five words of a pupil cue (son, daughter, child, kid,
   pupil, student, learner, Year 7 to 13, class, set, form, homework, method check).
   Unsure items, disagreements between the local rules and the model, fuzzy matches and
   word-names go to a review queue for a person. Output per call: the scrubbed transcript,
   a list of flags (turn, placeholder, role, why) and counts. Never the removed values in
   logs.
7. **Second check** on the final text, as rule 11, refusing on any identifier shape.

Test it on made-up transcripts first. Write 60 or more with someone who has not seen the
rules: coach and school staff talking, other teachers named, parents named, pupils by full
name, first name, nickname, initial, misheard spelling, and names that are words. Mark
every name with its role, in the same JSON shape as the bench sets. Keep a third unseen.
Then, inside the provider's approved environment only, two people annotate 150 to 300
real transcripts. Report recall per pupil-name mention by type, the share of calls leaking
any pupil name, over-redaction and cost. If 300 mentions show no misses, the miss rate is
under 1% at 95% confidence (the rule of three, 3/n).

## First steps

1. Run the tests and the three bench sets, and confirm the figures above.
2. Ask the person you work for where transcripts live, their format (speaker labels,
   timestamps), which metadata names the speakers, and which AI routes are approved.
3. Write a made-up transcript test set with someone who has not seen your rules, and keep
   a third of it unseen.
4. Build the transcript layer and measure it on that set, without the model pass.
5. Add the model pass only on an approved route, and measure it on the same set.
6. Put the flag queue in front of a person before anything is stored or shared.
