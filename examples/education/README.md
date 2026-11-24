# Education example

School text: support tickets, teacher and parent emails, chat, Slack, exports, logs,
report comments and SEN notes, where most names are pupils on a class list. hush 0.1.0
was built for this text; `hush.toml` here gives the same results with 0.2.0.

```
python3 -m hush scrub --config examples/education/hush.toml \
    --people examples/education/class-9X.csv examples/education/ticket.txt
python3 -m hush table examples/education/export.csv /tmp/export.out.csv \
    --config examples/education/hush.toml --preset dataset
python3 bench/bench.py bench/education/cases_3.json --config examples/education/hush.toml
```

## What the config adds

- **School vocabulary** (`keep.txt`, 155 words): terms, roles, subjects, exam words, maths
  names such as Pythagoras and Pascal, and homework-platform words. With the general list,
  this is hush 0.1.0's built-in vocabulary, word for word.
- **Unique Pupil Numbers and Unique Learner Numbers** as two detectors, found wherever they
  sit, URL paths included.
- **School columns** in a class list or export: Student, Pupil, Learner, Student username,
  School email, UPN, ULN.
- **Login labels** `pupil`, `student` and `learner`, so "pupil: jdoe23" is a login.
- **Role** `student`, so a class-list pupil is `[student 1]` and an adult `[person 1]`.

The class list is passed per school with `--people` (or `people=` in Python), and a staff
list with `--staff`. `class-9X.csv` shows the shape: Forename, Surname, Preferred,
Username, UPN. Pass the school's whole roll if you can.

## The ticket

`ticket.txt` with `class-9X.csv`:

```
Aisha hasn't logged in since Monday, so I reset her password (username akhan23,
UPN K801200345017). grace okafor said the Mark Scheme for task 3 was wrong.
Will is off sick this week. Will you check whether his Compulsory homework still shows?
```

becomes

```
[student 1] hasn't logged in since Monday, so I reset her password (username [username 1],
UPN [UPN 1]). [student 2] said the Mark Scheme for task 3 was wrong.
[student 3] is off sick this week. Will you check whether his Compulsory homework still shows?
```

"Will is off sick" loses Will, who is on the class list as William Baker. "Will you check"
keeps the verb. "Mark Scheme" stays.

## Measured figures

Three synthetic school sets in `bench/education/`, each written by a separate AI tester
that never saw the code, with the class list a school would hold. The rules were tuned on
sets 1 and 2; set 3 was held out.

- **Set 1**: 150 cases, 784 pupil-name sightings, 40 texts with no names.
- **Set 2**: 80 cases, 356 sightings, 30 texts with no names.
- **Set 3**: 60 cases, 221 sightings, 25 texts with no names. Held out.

Pupil names caught, with this config:

| | patterns only | + first-name list | + class list | `share` preset |
|---|---|---|---|---|
| set 1 (tuned on) | 64.7% | 87.5% | 96.9% | 97.7% |
| set 2 (tuned on) | 68.0% | 81.7% | 90.4% | 92.4% |
| **set 3 (held out)** | **70.6%** | **80.5%** | **90.5%** | **90.5%** |

Set 3 in more detail:

| | patterns only | `share` |
|---|---|---|
| pupils on the class list (138 sightings) | 69.6% | 97.1% |
| nicknames, initials, misreads of class-list pupils (45) | 51.1% | 62.2% |
| pupils not on the class list (38) | 97.4% | 100% |
| adults (97) | 92.8% | 95.9% |
| logins (35) | 42.9% | 88.6% |
| email, phone, UPN, ULN, date of birth, postcode (112) | 96.3 to 100% | 96.3 to 100% |
| texts with no names that still lost a word (of 25) | 22 | 3 |
| texts restored exactly from tokens (of 60) | 60 | 58 |

Every `+ first-name list`, `+ class list`, `share` and `logs` figure on all three sets is
the same as hush 0.1.0's. Two columns moved, both for a known reason:

- **Patterns only**: UPN on set 1 went from 96.2% to 100% and ULN on set 3 from 90.9% to
  100%, with 27 extra names taken on set 3 where 0.1.0 took 29. In 0.1.0 the UPN and ULN
  rules sat in the pupil layer, which "core alone" left out; they are now this config's
  detectors and run in every column.
- **The first-name list in any case, without the class list** (a bench column, not a
  preset): set 2 went from 85.1% to 86.0% and set 3 from 81.4% to 81.9%, with 57 exact
  restores on set 3 where 0.1.0 had 56. 0.2.0 takes a lower-case surname after a lower-case
  first name ("daniel okafor"). The presets that use any case also pass the class list,
  and with it the figures did not move.

The two inexact restores are one pupil written in two casings ("taylor reid", "Taylor
Reid"): one token, so both come back in the first casing. One fault that set 3 showed was
fixed after its first run (the first-name list took "jordan" out of "@jordan.p"), so the
logins figure on set 3 counts as in-sample. 38 off-list pupils is a small sample; set 2's
92 gave 94.6%.

## What it misses in school text

- Nicknames and initials of class-list pupils: "Alex P.", "Kiran S.", "TJ", "Mo". Add known
  nicknames to the class list's Preferred column.
- A pupil's name in lower case when it is also a word and nothing after it marks a person:
  "ruby", "faith", "storm" in quick chat.
- Logins with no dot, digit or label ("whopkins").
- School names stay, like any organisation name.

## Before using it on real school text

1. Always pass the school's roll.
2. Where a pupil table is available, build the first-name list from it (every distinct
   first name with a count); `tools/build_names.py` shows the shape.
3. Transcripts and tickets that mention pupils are personal data about children. Measure on
   real text only inside a route your data protection lead has approved.
