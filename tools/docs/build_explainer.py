"""Build docs/explainer.html.

    python3 build_explainer.py OUT_HTML PRESET_DEMO_JSON

Every figure is typed from the output of bench/student_bench.py on the three test sets in
this repository. PRESET_DEMO_JSON is the output of preset_demo.py, run from the repository
root."""
import html
import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
DEMO = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

# --- figure 1: pupil names caught, by what hush is given (dot plot) -----------------
ROWS = [  # label, set 1 (tuned on), set 3 (held out)
    ("Core alone", 64.7, 70.6),
    ("+ first-name list", 87.5, 80.5),
    ("+ class list", 96.9, 90.5),
    ("share preset", 97.7, 90.5),
]


def fig_dots():
    w, left, x0, x1, top, step = 380, 0, 124, 366, 34, 44
    lo, hi = 50.0, 100.0

    def x(v):
        return x0 + (v - lo) / (hi - lo) * (x1 - x0)

    h = top + step * len(ROWS) + 26
    parts = ['<svg viewBox="0 0 %d %d" role="img" aria-labelledby="f1t f1d" class="chart">' % (w, h),
             '<title id="f1t">Pupil names caught, by what hush is given</title>',
             '<desc id="f1d">Dot plot. For each configuration, the share of pupil-name '
             'sightings caught on the set the rules were tuned on and on the held-out set.</desc>']
    for v in range(50, 101, 10):
        parts.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" class="grid"/>'
                     % (x(v), x(v), top - 14, h - 22))
        parts.append('<text x="%.1f" y="%d" class="tick" text-anchor="middle">%d%%</text>'
                     % (x(v), h - 6, v))
    for i, (label, a, b) in enumerate(ROWS):
        y = top + step * i + 10
        parts.append('<text x="%d" y="%d" class="row">%s</text>' % (left, y + 4, html.escape(label)))
        parts.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" class="link"/>'
                     % (x(min(a, b)), x(max(a, b)), y, y))
        for v, cls, name in ((a, "s1", "set 1, tuned on"), (b, "s2", "set 3, held out")):
            parts.append('<g class="mark"><circle cx="%.1f" cy="%d" r="11" class="hit"/>'
                         '<circle cx="%.1f" cy="%d" r="6" class="%s"/>'
                         '<title>%s, %s: %.1f%%</title></g>'
                         % (x(v), y, x(v), y, cls, html.escape(label), name, v))
        if i == len(ROWS) - 1:
            parts.append('<text x="%.1f" y="%d" class="val" text-anchor="middle">%.1f%%</text>'
                         % (x(a), y - 12, a))
            parts.append('<text x="%.1f" y="%d" class="val" text-anchor="middle">%.1f%%</text>'
                         % (x(b), y + 22, b))
    parts.append('</svg>')
    return "\n".join(parts)


def esc(s):
    return html.escape(s, quote=False)


def short_tokens(s):
    """Show ask-ai tokens shortened, so the line fits."""
    import re
    return re.sub(r"<P[0-9A-F]{16}_([A-Z]+)_(\d{4})_[0-9A-F]{16}>",
                  lambda m: "\x00%s_%s\x01" % (m.group(1), m.group(2)), s)


ASK = esc(short_tokens(DEMO["ask-ai"])).replace("\x00", '<span class="tok">&lt;P…_').replace(
    "\x01", "_…&gt;</span>")

BEFORE = """Hi Mrs Pemberton,

Thanks for getting in touch. Aisha hasn't logged in since Monday, so I reset her password
(username akhan23, UPN K801200345017). grace okafor said the Mark Scheme for task 3 was
wrong; I've passed that to the content team.

Will is off sick this week. Will you check whether his Compulsory homework still shows?
Bartek and Zoe Lark both finished their Independent Learning. Musa Bangura joined 9X
yesterday and needs adding to the class.

Kind regards,
Ms Lindqvist"""

AFTER = """Hi Mrs [person 1],

Thanks for getting in touch. [student 1] hasn't logged in since Monday, so I reset her password
(username [username 1], UPN [UPN 1]). [student 2] said the Mark Scheme for task 3 was
wrong; I've passed that to the content team.

[student 3] is off sick this week. Will you check whether his Compulsory homework still shows?
[student 4] and [student 5] both finished their Independent Learning. [person 2] joined 9X
yesterday and needs adding to the class.

Kind regards,
Ms [person 3]"""


def mark_after(s):
    import re
    return re.sub(r"\[[a-zA-Z ]+ \d+\]", lambda m: '<mark>%s</mark>' % m.group(0), esc(s))


PAGE = """<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pupil-name scrubber</title>
<style>
:root {
  color-scheme: light;
  --bg: #fcfcfb; --surface: #f3f2ef; --ink: #0b0b0b; --ink-2: #52514e; --ink-3: #75746f;
  --rule: #dcdbd6; --accent: #2a78d6; --s1: #2a78d6; --s2: #eb6834; --mark: #fde9a8;
  --mark-ink: #0b0b0b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --bg: #1a1a19; --surface: #242423; --ink: #f0efec; --ink-2: #c3c2b7; --ink-3: #9a998f;
    --rule: #3a3a37; --accent: #3987e5; --s1: #3987e5; --s2: #d95926; --mark: #4a3f12;
    --mark-ink: #f0efec;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #1a1a19; --surface: #242423; --ink: #f0efec; --ink-2: #c3c2b7; --ink-3: #9a998f;
  --rule: #3a3a37; --accent: #3987e5; --s1: #3987e5; --s2: #d95926; --mark: #4a3f12;
  --mark-ink: #f0efec;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 17px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 2.1rem; line-height: 1.15; margin: 0 0 6px; letter-spacing: -0.01em; }
h2 { font-size: 1.3rem; margin: 44px 0 10px; padding-top: 12px; border-top: 1px solid var(--rule); }
h3 { font-size: 1.02rem; margin: 22px 0 6px; }
p, li { color: var(--ink); }
.lede { font-size: 1.15rem; color: var(--ink-2); margin: 0 0 8px; }
.byline { color: var(--ink-3); font-size: 0.9rem; margin: 0; }
.note { color: var(--ink-2); font-size: 0.92rem; }
.theme { position: fixed; top: 12px; right: 12px; border: 1px solid var(--rule);
  background: var(--surface); color: var(--ink-2); border-radius: 6px; padding: 4px 10px;
  font: inherit; font-size: 0.85rem; cursor: pointer; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px;
  margin: 16px 0; }
.tile { background: var(--surface); border-radius: 8px; padding: 12px 14px; }
.tile b { display: block; font-size: 1.7rem; line-height: 1.1; font-variant-numeric: tabular-nums; }
.tile span { color: var(--ink-2); font-size: 0.88rem; }
pre, code { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
code { font-size: 0.9em; background: var(--surface); padding: 1px 4px; border-radius: 4px; }
pre { background: var(--surface); padding: 12px 14px; border-radius: 8px; overflow-x: auto;
  font-size: 0.8rem; line-height: 1.5; white-space: pre-wrap; margin: 6px 0 0; }
mark { background: var(--mark); color: var(--mark-ink); border-radius: 3px; padding: 0 1px; }
.pair { display: grid; grid-template-columns: 1fr; gap: 12px; }
@media (min-width: 900px) { main { max-width: 1000px; } .pair { grid-template-columns: 1fr 1fr; } }
.label { font-size: 0.8rem; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.06em; }
table { border-collapse: collapse; width: 100%; font-size: 0.92rem; margin: 10px 0; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { color: var(--ink-2); font-weight: 600; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.wrap { overflow-x: auto; }
.tok { color: var(--accent); }
a { color: var(--accent); }
ol.steps { padding-left: 0; list-style: none; counter-reset: s; margin: 12px 0; }
ol.steps li { counter-increment: s; position: relative; padding: 0 0 14px 44px; }
ol.steps li::before { content: counter(s); position: absolute; left: 0; top: 0; width: 28px;
  height: 28px; border-radius: 50%%; background: var(--surface); border: 1px solid var(--rule);
  display: grid; place-items: center; font-size: 0.85rem; font-weight: 600; color: var(--ink-2); }
ol.steps li::after { content: ""; position: absolute; left: 14px; top: 30px; bottom: 2px;
  width: 1px; background: var(--rule); }
ol.steps li:last-child::after { display: none; }
ol.steps li.check::before { content: "✓"; color: var(--accent); }
.chart { width: 100%%; max-width: 520px; height: auto; display: block; margin: 8px 0 4px; }
.chart .grid { stroke: var(--rule); stroke-width: 1; }
.chart .tick { fill: var(--ink-3); font-size: 11px; }
.chart .row { fill: var(--ink); font-size: 13px; }
.chart .val { fill: var(--ink-2); font-size: 12px; font-variant-numeric: tabular-nums; }
.chart .link { stroke: var(--ink-3); stroke-width: 2; stroke-linecap: round; }
.chart .s1 { fill: var(--s1); stroke: var(--bg); stroke-width: 2; }
.chart .s2 { fill: var(--s2); stroke: var(--bg); stroke-width: 2; }
.chart .hit { fill: transparent; }
.chart .mark:hover .s1, .chart .mark:hover .s2 { stroke: var(--ink); }
.legend { display: flex; gap: 18px; flex-wrap: wrap; font-size: 0.88rem; color: var(--ink-2); margin: 6px 0 0; }
.legend i { display: inline-block; width: 11px; height: 11px; border-radius: 50%%; margin-right: 6px;
  vertical-align: -1px; }
details { margin: 4px 0 12px; }
summary { cursor: pointer; color: var(--accent); font-size: 0.92rem; }
footer { margin-top: 48px; padding-top: 14px; border-top: 1px solid var(--rule); color: var(--ink-3);
  font-size: 0.86rem; }
@media print { .theme { display: none; } }
</style>
</head>
<body>
<button class="theme" type="button" id="theme" aria-label="Switch light or dark">Light / dark</button>
<main>

<h1>Pupil-name scrubber</h1>
<p class="lede">Takes pupils' names and other personal data out of text before it goes to an
AI model, a Slack channel, a spreadsheet or a log tool.</p>
<p class="byline">pupil-name-scrubber · Python package <code>hush</code> 0.1.0 · standard
library only, no network, no model call</p>

<h2>In short</h2>
<ul>
<li>It looks for pupils first: in the school's class list, then in 22,643 first names from
the ONS baby-name tables, then by context ("Will is off sick" but not "Will you check").</li>
<li>On made-up school text it had never seen, it caught <b>97.1%</b> of pupil-name sightings
where the pupil was on the class list, and <b>90.5%</b> of all of them. With no class list,
80.5%.</li>
<li>Nicknames and initials are its weak spot: about six in ten caught.</li>
<li>Five presets for five jobs. One of them puts the real names back into an AI model's
answer.</li>
</ul>
<div class="tiles">
<div class="tile"><b>97.1%</b><span>pupils on the class list, caught (held-out set)</span></div>
<div class="tile"><b>90.5%</b><span>all pupil-name sightings, caught (held-out set)</span></div>
<div class="tile"><b>3 of 25</b><span>name-free texts that lost a word (22 of 25 with the core alone)</span></div>
</div>

<h2>What it does to a ticket</h2>
<p>A reply to a teacher, run with the class list and the default <code>share</code> preset:</p>
<div class="pair">
<div><div class="label">Before</div><pre>%(before)s</pre></div>
<div><div class="label">After</div><pre>%(after)s</pre></div>
</div>
<p class="note">"Will is off sick" loses Will, who is on the class list as William Baker.
"Will you check" keeps the verb. "Mark Scheme" and "Independent Learning" stay. Musa Bangura is
not on the class list; the first-name list finds him.</p>

<h2>Five presets</h2>
<p>The same sentence through each one:</p>
<pre>%(text)s</pre>
<div class="wrap"><table>
<tr><th>Preset</th><th>Output</th><th>Use it for</th></tr>
<tr><td><code>ask-ai</code></td><td>%(ask)s</td><td>Sending a ticket or email to an AI model. The tokens go back to the real names in its answer.</td></tr>
<tr><td><code>share</code></td><td>%(share)s</td><td>Slack, Jira, slides, case studies, bug reports.</td></tr>
<tr><td><code>dataset</code></td><td>%(dataset)s</td><td>Exports for an analyst. With the same key, the same pupil gets the same code in every file.</td></tr>
<tr><td><code>demo</code></td><td>%(demo)s</td><td>Training material and test data. Made-up names keep the sex of the name they replace.</td></tr>
<tr><td><code>logs</code></td><td>%(logs)s</td><td>Logs and error reports. Turns off the guess at capitalised names, so code and class names survive.</td></tr>
</table></div>
<p class="note"><code>share</code> and <code>logs</code> refuse to give any output when the
second check still finds an identifier. <code>dataset</code> and <code>demo</code> warn.
<code>grace's</code> goes because Grace Okafor is on the class list and a possessive marks a
person.</p>

<h2>How it finds a pupil</h2>
<p>In this order. Each step only sees what the steps before it left.</p>
<ol class="steps">
<li><b>Emails and links</b>, whole, so a name inside an address never splits it.</li>
<li><b>Titled names.</b> "Mrs Pemberton" keeps "Mrs" and loses the name.</li>
<li><b>Logins, handles, UPNs and ULNs</b> by their shape, plus the class list's own logins.</li>
<li><b>The class list.</b> Full names in either order, first, preferred and last names alone,
any case, possessives, accents folded ("Zoe" finds Zoë), and the rows of any table pasted into
the text.</li>
<li><b>Names that are also words</b> (Grace, Will, Summer, Hope) only in a name's place: not
after "the", not before "Scheme" or "Term", in lower case only before a verb ("grace hasn't
logged in").</li>
<li><b>The first-name list</b>, any name given to 10 or more babies in England and Wales
since 1996. Not after "in" or "from".</li>
<li><b>Screenshot misreads</b> of class-list names: one letter out, or 0, 1, 5 for o, l, s.</li>
<li><b>Identifier rules</b> from the core: NHS and NI numbers, bank details, cards, phones,
postcodes, addresses, dates, long numbers, codes, passwords.</li>
<li><b>A guess</b> at capitalised names from their neighbours, for anyone left. It must not be a
run of ordinary words: "Simultaneous Equations" stays, "Grace Baker" goes.</li>
<li class="check"><b>A second check</b>, written separately, reads the result and refuses it
if an identifier shape is still there.</li>
</ol>

<h2>How well it works</h2>
<p>Three testers, each a separate AI agent that never saw the code, wrote made-up school text:
support notes, emails, chat, Slack, CSV and JSON exports, logs, report comments, SEN notes,
screenshot text. Each case comes with the class list a school would hold and every piece of
personal data marked. The rules were tuned on sets 1 and 2. <b>Set 3 was held out from the
tuning, so its figures are the ones to expect on new text.</b></p>

<h3>Pupil names caught, by what hush is given</h3>
<div class="legend"><span><i style="background:var(--s1)"></i>Set 1, tuned on (784 sightings)</span>
<span><i style="background:var(--s2)"></i>Set 3, held out (221 sightings)</span></div>
%(fig1)s
<details><summary>Show the numbers</summary>
<div class="wrap"><table>
<tr><th>Pupil names caught</th><th class="n">core alone</th><th class="n">+ first-name list</th><th class="n">+ class list</th><th class="n">share preset</th></tr>
<tr><td>Set 1 (150 cases, tuned on)</td><td class="n">64.7%%</td><td class="n">87.5%%</td><td class="n">96.9%%</td><td class="n">97.7%%</td></tr>
<tr><td>Set 2 (80 cases, tuned on)</td><td class="n">68.0%%</td><td class="n">81.7%%</td><td class="n">90.4%%</td><td class="n">92.4%%</td></tr>
<tr><td>Set 3 (60 cases, held out)</td><td class="n">70.6%%</td><td class="n">80.5%%</td><td class="n">90.5%%</td><td class="n">90.5%%</td></tr>
</table></div>
</details>
<p class="note">The class list is the single largest gain. The gap between set 1 and set 3 is
what tuning buys on text you have seen; expect set 3's figures on real text, or a little
lower.</p>

<h3>The held-out set, in detail</h3>
<div class="wrap"><table>
<tr><th>Set 3, sightings</th><th class="n">core alone</th><th class="n">share preset</th></tr>
<tr><td>Pupils on the class list (138)</td><td class="n">69.6%%</td><td class="n">97.1%%</td></tr>
<tr><td>Nicknames, initials and misreads of class-list pupils (45)</td><td class="n">51.1%%</td><td class="n">62.2%%</td></tr>
<tr><td>Pupils not on the class list (38)</td><td class="n">97.4%%</td><td class="n">100%%</td></tr>
<tr><td>Adults: teachers, parents, staff (97)</td><td class="n">92.8%%</td><td class="n">95.9%%</td></tr>
<tr><td>Logins and handles (35)</td><td class="n">42.9%%</td><td class="n">88.6%%</td></tr>
<tr><td>Email, phone, UPN, ULN, date of birth, postcode (112)</td><td class="n">90.9 to 100%%</td><td class="n">96.3 to 100%%</td></tr>
<tr><td>Name-free texts that lost a word (25)</td><td class="n">22</td><td class="n">3</td></tr>
<tr><td>Texts restored exactly by <code>ask-ai</code> (60)</td><td class="n">60</td><td class="n">58</td></tr>
</table></div>
<p class="note">A sighting counts as caught when none of its letters or digits is left in
place; a kept title ("Mrs") does not count as a leak. The two inexact restores are one pupil
written two ways ("taylor reid", "Taylor Reid"): one token, so both come back in the first
casing. One fault that set 3 showed was fixed after its first run: the first-name list took
"jordan" out of the handle "@jordan.p" before the handle rule could see it whole. The logins
figure therefore counts as in-sample.</p>

<h3>Why the class list comes first</h3>
<p>On set 3, pupils on the class list were caught 69.6%% of the time by the core alone,
82.6%% with the first-name list added, and 97.1%% once the class list was passed. A name the
tool has been told about is matched exactly, in any order and any case. A name it has not been
told about has to be guessed from context, and guesses miss. A school already holds the class
list.</p>

<h2>What it misses</h2>
<ul>
<li>Nicknames and initials of class-list pupils ("Alex P.", "Kiran S.", "TJ"). Put known
nicknames in the class list's Preferred column.</li>
<li>Names in lower case that are also words, with nothing after them that marks a person:
"ruby", "faith", "storm" in quick chat.</li>
<li>Bad screenshot misreads ("Wel Chen", "Bi11").</li>
<li>Rare names that are also words, alone ("Ash", "Moss"), and logins with no dot, digit or
label ("whopkins").</li>
<li>It takes some words that are not people: towns ("Bradford", "Penrith"), places that are
first names (Paris, Jordan, India), and company names ("Taylor Wimpey").</li>
<li>School and organisation names stay. So does anything that identifies without a name: "the
only Year 9 with a cochlear implant". No pattern tool can see that.</li>
</ul>

<h2>Before using it on real text</h2>
<ol>
<li>Always pass the class list, or the school's whole roll. It is the largest gain.</li>
<li>Where a pupil table is available, build the first-name list from it (every distinct first
name with a count) instead of the ONS file; <code>tools/build_names.py</code> shows the
shape.</li>
<li>Measure on real text before trusting these numbers: a few hundred real tickets, scrubbed,
read by someone the data protection officer trusts, and scored with the bench.</li>
<li>Keep the second check on for anything that leaves your own systems.</li>
</ol>

<h2>Call transcripts</h2>
<p><a href="transcripts-plan.html">transcripts-plan.html</a> describes an extension for
customer call transcripts between a support coach and school staff: remove every name that is
not a known speaker's, flag the likely pupils, and use a language model only to judge the
candidates the rules found. It is a design and is not built yet.</p>

<h2>Try it</h2>
<pre>python3 -m hush presets
python3 -m hush scrub --roster examples/class-9X.csv examples/ticket.txt
python3 -m hush table examples/export.csv /tmp/export.out.csv --preset dataset
python3 -m unittest discover -s tests
python3 bench/student_bench.py bench/student_cases_3.json</pre>
<p class="note">Run from the repository root. Tested on Python 3.14. The README has the
Python interface, the class-list format and how to pass a key for <code>dataset</code> and
<code>demo</code>.</p>

<footer>
<p>Code: MIT licence. First names derived from the ONS's "Baby names in England and Wales:
1996 to 2025" under the Open Government Licence v3.0. English words from SCOWL (Debian
<code>wbritish</code>), copyright Kevin Atkinson and others. All names in this page and the
test sets are made up.</p>
</footer>
</main>
<script>
(function () {
  var root = document.documentElement, key = "hush-theme";
  try { var saved = localStorage.getItem(key); if (saved) root.dataset.theme = saved; } catch (e) {}
  document.getElementById("theme").addEventListener("click", function () {
    var dark = root.dataset.theme ? root.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem(key, root.dataset.theme); } catch (e) {}
  });
})();
</script>
</body>
</html>
"""

FILL = {
    "before": esc(BEFORE), "after": mark_after(AFTER), "text": esc(DEMO["text"]),
    "ask": ASK, "share": esc(DEMO["share"]), "dataset": esc(DEMO["dataset"]),
    "demo": esc(DEMO["demo"]), "logs": esc(DEMO["logs"]),
    "fig1": fig_dots(),
}
page = PAGE.replace("%%", "%")
for name, value in FILL.items():
    page = page.replace("%%(%s)s" % name, value)
assert "%(" not in page
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(page, encoding="utf-8")
print("wrote", OUT, len(page), "bytes")
