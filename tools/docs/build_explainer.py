"""Build docs/explainer.html.

    python3 build_explainer.py OUT_HTML PRESET_DEMO_JSON

The public-benchmark figures are typed from runs/tables.md of bench/public (hush's share
preset with no config, Presidio and GLiNER from the same harness). The bench figures are
typed from the output of bench/bench.py on bench/general/cases.json (no config) and
bench/education/cases_3.json (examples/education/hush.toml). Update them when either
changes. PRESET_DEMO_JSON is the output of preset_demo.py, run from the
repository root: the preset table and the support call before and after come from it."""
import html
import json
import re
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
DEMO = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

# --- figure 1: share of personal data caught on five public sets (dot plot) ---------
# set, hush share preset, Presidio, GLiNER (30 labels): recall over every gold span.
COMPARE = [
    ("PII-TRACE", 94.3, 62.3, 53.0),
    ("Nemotron-PII", 76.1, 63.5, 60.6),
    ("Nemotron transcripts", 76.0, 66.1, 58.9),
    ("Chat lines", 97.2, 65.2, 96.0),
    ("TAB (court cases)", 68.1, 72.6, 57.5),
]


def fig_compare():
    w, left, x0, x1, top, step = 380, 0, 150, 366, 34, 40
    lo, hi = 40.0, 100.0

    def x(v):
        return x0 + (v - lo) / (hi - lo) * (x1 - x0)

    h = top + step * len(COMPARE) + 26
    parts = ['<svg viewBox="0 0 %d %d" role="img" aria-labelledby="f0t f0d" class="chart">' % (w, h),
             '<title id="f0t">Personal data caught on five public test sets</title>',
             '<desc id="f0d">Dot plot. For each public set, the share of marked personal data '
             'that hush, Presidio and GLiNER removed.</desc>']
    for v in range(40, 101, 10):
        parts.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" class="grid"/>'
                     % (x(v), x(v), top - 14, h - 22))
        parts.append('<text x="%.1f" y="%d" class="tick" text-anchor="middle">%d%%</text>'
                     % (x(v), h - 6, v))
    for i, (label, ours, presidio, gliner) in enumerate(COMPARE):
        y = top + step * i + 10
        parts.append('<text x="%d" y="%d" class="row">%s</text>' % (left, y + 4, html.escape(label)))
        values = (ours, presidio, gliner)
        parts.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" class="link"/>'
                     % (x(min(values)), x(max(values)), y, y))
        for v, cls, name in ((gliner, "s3", "GLiNER"), (presidio, "s2", "Presidio"),
                             (ours, "s1", "hush, share preset")):
            parts.append('<g class="mark"><circle cx="%.1f" cy="%d" r="11" class="hit"/>'
                         '<circle cx="%.1f" cy="%d" r="6" class="%s"/>'
                         '<title>%s, %s: %.1f%%</title></g>'
                         % (x(v), y, x(v), y, cls, html.escape(label), name, v))
    parts.append('</svg>')
    return "\n".join(parts)


# --- figure 2: names caught, by what hush is given (dot plot) -----------------------
ROWS = [  # label, general set (no config), education set 3 (education config)
    ("Patterns only", 73.6, 73.3),
    ("+ first-name list", 80.7, 82.4),
    ("+ known people", 86.0, 91.0),
    ("share preset", 88.8, 91.0),
]


def fig_dots():
    w, left, x0, x1, top, step = 380, 0, 124, 366, 34, 44
    lo, hi = 50.0, 100.0

    def x(v):
        return x0 + (v - lo) / (hi - lo) * (x1 - x0)

    h = top + step * len(ROWS) + 26
    parts = ['<svg viewBox="0 0 %d %d" role="img" aria-labelledby="f1t f1d" class="chart">' % (w, h),
             '<title id="f1t">Names caught, by what hush is given</title>',
             '<desc id="f1d">Dot plot. For each configuration, the share of name sightings '
             'caught on the general test set and on the held-out school set.</desc>']
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
        for v, cls, name in ((a, "s1", "general set"), (b, "s2", "school set 3, held out")):
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
    return re.sub(r"<P[0-9A-F]{16}_([A-Z_]+?)_(\d{4})_[0-9A-F]{16}>",
                  lambda m: "\x00%s_%s\x01" % (m.group(1), m.group(2)), s)


ASK = esc(short_tokens(DEMO["ask-ai"])).replace("\x00", '<span class="tok">&lt;P…_').replace(
    "\x01", "_…&gt;</span>")


def lines(text, keep):
    """The call's lines whose numbers are in keep, so the page shows a short stretch."""
    rows = text.splitlines()
    return "\n".join(rows[i] for i in keep if i < len(rows))


SHOWN = (1, 2, 3, 4, 5, 6, 7)
BEFORE = lines(DEMO["call_before"], SHOWN)
AFTER = lines(DEMO["call_after"], SHOWN)
FLAGS = ", ".join("%s (near \u201c%s\u201d)" % (f["shown"], f["why"][len("role cue: "):])
                  for f in DEMO["call_flags"] if f["why"].startswith("role cue: "))


def mark_after(s):
    return re.sub(r"\[[a-zA-Z ]+ \d+\]", lambda m: '<mark>%s</mark>' % m.group(0), esc(s))


PAGE = """<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transcript PII scrubber</title>
<style>
:root {
  color-scheme: light;
  --bg: #fcfcfb; --surface: #f3f2ef; --ink: #0b0b0b; --ink-2: #52514e; --ink-3: #75746f;
  --rule: #dcdbd6; --accent: #2a78d6; --s1: #2a78d6; --s2: #eb6834; --s3: #7a7a74; --mark: #fde9a8;
  --mark-ink: #0b0b0b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --bg: #1a1a19; --surface: #242423; --ink: #f0efec; --ink-2: #c3c2b7; --ink-3: #9a998f;
    --rule: #3a3a37; --accent: #3987e5; --s1: #3987e5; --s2: #d95926; --s3: #9a9a92; --mark: #4a3f12;
    --mark-ink: #f0efec;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #1a1a19; --surface: #242423; --ink: #f0efec; --ink-2: #c3c2b7; --ink-3: #9a998f;
  --rule: #3a3a37; --accent: #3987e5; --s1: #3987e5; --s2: #d95926; --s3: #9a9a92; --mark: #4a3f12;
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
.chart .s3 { fill: var(--s3); stroke: var(--bg); stroke-width: 2; }
.chart .hit { fill: transparent; }
.chart .mark:hover .s1, .chart .mark:hover .s2, .chart .mark:hover .s3 { stroke: var(--ink); }
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

<h1>Transcript PII scrubber</h1>
<p class="lede">Checks a transcript, or any other text, for the kinds of personal data you
choose, and replaces them before the text goes to an AI model, a chat, a ticket, a dataset
or a log.</p>
<p class="byline">Transcript PII scrubber · Python package <code>hush</code> 0.2.0 · standard
library only, no network, no model call</p>

<h2>In short</h2>
<ul>
<li>On five public PII test sets, with no config, its <code>share</code> preset removed more
of the marked personal data than Presidio and GLiNER on four of them, and less on the
court cases of TAB. It was tuned on three of the five; the two held out are PII-TRACE
(94.3%%, against 62.3%% and 53.0%%) and TAB (68.1%%, against 72.6%% and 57.5%%).</li>
<li>A config file says what to look for: which detector packs run, who the known people
are, which names to keep, which words are never a name, your own patterns, and which kinds
are only flagged for review.</li>
<li>Nicknames, initials, names that are also words and towns on their own are its weak
spots.</li>
<li>Five presets for five jobs. One of them puts the real values back into an AI model's
answer.</li>
</ul>
<div class="tiles">
<div class="tile"><b>94.3%%</b><span>personal data removed, PII-TRACE, held out</span></div>
<div class="tile"><b>0 of 218</b><span>PII-TRACE dialogues with a name left</span></div>
<div class="tile"><b>88.8%%</b><span>names caught, its own general set, no config</span></div>
</div>

<h2>How it compares</h2>
<p>Five openly licensed test sets, each scored the same way for every tool: a marked span
counts as removed when none of its letters or digits is left. hush ran its
<code>share</code> preset with no config; Presidio ran with its defaults and spaCy's
<code>en_core_web_lg</code>; GLiNER is <code>knowledgator/gliner-pii-large-v1.0</code> with
30 labels at a threshold of 0.3.</p>
<div class="legend"><span><i style="background:var(--s1)"></i>hush, share preset</span>
<span><i style="background:var(--s2)"></i>Presidio</span>
<span><i style="background:var(--s3)"></i>GLiNER</span></div>
%(fig0)s
<div class="wrap"><table>
<tr><th>Personal data removed</th><th class="n">hush</th><th class="n">Presidio</th><th class="n">GLiNER</th></tr>
<tr><td>PII-TRACE, 500 dialogues (held out)</td><td class="n">94.3%%</td><td class="n">62.3%%</td><td class="n">53.0%%</td></tr>
<tr><td>Nemotron-PII, 1,000 documents</td><td class="n">76.1%%</td><td class="n">63.5%%</td><td class="n">60.6%%</td></tr>
<tr><td>Nemotron-PII transcripts, 196</td><td class="n">76.0%%</td><td class="n">66.1%%</td><td class="n">58.9%%</td></tr>
<tr><td>Synthetic chat lines, 500</td><td class="n">97.2%%</td><td class="n">65.2%%</td><td class="n">96.0%%</td></tr>
<tr><td>TAB, 127 court cases (held out)</td><td class="n">68.1%%</td><td class="n">72.6%%</td><td class="n">57.5%%</td></tr>
</table></div>
<div class="wrap"><table>
<tr><th>Words wrongly removed, per 1,000</th><th class="n">hush</th><th class="n">Presidio</th><th class="n">GLiNER</th></tr>
<tr><td>PII-TRACE</td><td class="n">0.7</td><td class="n">1.8</td><td class="n">5.8</td></tr>
<tr><td>Nemotron-PII</td><td class="n">9.7</td><td class="n">12.7</td><td class="n">1.1</td></tr>
<tr><td>Nemotron-PII transcripts</td><td class="n">6.2</td><td class="n">11.8</td><td class="n">0.9</td></tr>
<tr><td>Synthetic chat lines</td><td class="n">0.0</td><td class="n">8.7</td><td class="n">0.0</td></tr>
<tr><td>TAB</td><td class="n">5.8</td><td class="n">15.4</td><td class="n">9.9</td></tr>
</table></div>
<ul class="note">
<li>All five sets are synthetic or legal text, not real call transcripts: no lower-case
names, fillers or misheard words. Real transcripts will be harder for every tool.</li>
<li>hush was tuned on the Nemotron sets and the chat lines. PII-TRACE and TAB were held
out, but their weak categories (PII-TRACE addresses and phone extensions, TAB's years) were
known from a first run before the address, phone and date rules were written.</li>
<li>PII-TRACE's names are invented words, which suits hush's "not an English word" rule and
flatters its name score. The Nemotron sets use realistic names.</li>
<li>Presidio ran with its defaults and GLiNER was not tuned either. GLiNER moved a lot with
its label list: with 10 plain labels in place of 30 it removed 84.1%% on PII-TRACE but
47.3%% on Nemotron-PII, and left a name in 1 chat line of 365 where hush left 30.</li>
<li>On TAB, Presidio
removes more addresses (79.9%%) and dates (98.9%%); hush removes more application and case
numbers (94.0%% against 5.6%%).</li>
<li><code>bench/public/</code> has the harness, the dataset sources and the commands.</li>
</ul>

<h2>What it does to a call</h2>
<p>Part of a support call, run with <code>examples/support-call/hush.toml</code>:</p>
<div class="pair">
<div><div class="label">Before</div><pre>%(before)s</pre></div>
<div><div class="label">After</div><pre>%(after)s</pre></div>
</div>
<p class="note">The agent is on the config's keep list and the customer is a speaker the
transcript names, so both stay. Everyone else goes. A removed name with a role word near it
is labelled by that role and flagged for a person to review: %(flags)s. The date of birth,
account reference and phone go; the order date stays and is flagged, because the config
says so.</p>

<h2>Five presets</h2>
<p>The same sentence through each one, with Gareth Lyle and Grace Okafor as known
customers:</p>
<pre>%(text)s</pre>
<div class="wrap"><table>
<tr><th>Preset</th><th>Output</th><th>Use it for</th></tr>
<tr><td><code>ask-ai</code></td><td>%(ask)s</td><td>Sending a transcript, ticket or email to an AI model. The tokens go back to the real values in its answer.</td></tr>
<tr><td><code>share</code></td><td>%(share)s</td><td>Chats, tickets, slides, case studies, bug reports.</td></tr>
<tr><td><code>dataset</code></td><td>%(dataset)s</td><td>Exports for an analyst. With the same key, the same person gets the same code in every file.</td></tr>
<tr><td><code>demo</code></td><td>%(demo)s</td><td>Training material and test data. Made-up names keep the sex of the name they replace.</td></tr>
<tr><td><code>logs</code></td><td>%(logs)s</td><td>Logs and error reports. Turns off the guess at capitalised names, so code and class names survive.</td></tr>
</table></div>
<p class="note"><code>ask-ai</code>, <code>share</code> and <code>logs</code> refuse to give
any output when the second check still finds an identifier. <code>dataset</code> and
<code>demo</code> warn. "Will you" keeps the verb; <code>grace's</code> goes because Grace
Okafor is a known customer and a possessive marks a person.</p>

<h2>What you choose</h2>
<div class="wrap"><table>
<tr><th>Setting</th><th>What it does</th></tr>
<tr><td>Packs</td><td><code>general</code> (emails, links, IPs, cards, IBANs, phones with extensions, street addresses and PO boxes, dates with times or no year, long numbers, codes, secrets, usernames), <code>uk</code> (NHS and NI numbers, sort codes, UK phones, postcodes, addresses), <code>north-america</code> (phones, a town with its state and ZIP, Canadian postcodes), <code>south-africa</code> (off by default). The second check reads for the same packs.</td></tr>
<tr><td>Known people</td><td>A CSV or a list of names: every form of each person goes, labelled by role ("[customer 1]").</td></tr>
<tr><td>Names to keep</td><td>Staff, agents, authors: never removed, in any form.</td></tr>
<tr><td>Words</td><td>Product, team and place names that look like names, kept; client names always removed.</td></tr>
<tr><td>Detectors</td><td>Your own patterns, such as an order or case reference, with a label.</td></tr>
<tr><td>Transcripts</td><td>Speaker labels kept, relabelled or read as text; role cues near a removed name.</td></tr>
<tr><td>Flags</td><td>Kinds left in place and listed for review, such as dates.</td></tr>
<tr><td>Years and warnings</td><td>Whether a year on its own goes (off by default), and how many ages, places, jobs, dates and rare details left in a text earn a warning.</td></tr>
</table></div>
<p class="note">Three worked configs are in <code>examples/</code>: support calls, a
document before an AI model reads it, and school text. The README lists every key.</p>

<h2>How it finds a name</h2>
<p>In this order. Each step only sees what the steps before it left.</p>
<ol class="steps">
<li><b>Emails, links and street addresses</b>, whole, so a name inside one never splits
it.</li>
<li><b>Names to keep</b>, in every form: "Priya Shah", "Shah, Priya", "Priya", "Ms Shah".</li>
<li><b>Names and IDs</b>, found together, the longer winning where two overlap: titled
names ("Mrs Pemberton" keeps "Mrs"), your own detectors, logins and handles, the known
people in any order and case, names that are also words only in a name's place, the
first-name list (22,643 names given to 10 or more babies in England and Wales since 1996),
and screenshot misreads.</li>
<li><b>Identifier rules</b> from the packs: numbers read out as words, phones, postcodes,
national numbers, bank details, cards, dates, long numbers, codes, passwords.</li>
<li><b>A guess</b> at capitalised names from their neighbours, for anyone left. It must not be
a run of ordinary words: "Project Alder Review" stays, "Grace Baker" goes.</li>
<li><b>Every other mention</b> of a name found, in any case: "phiri's" after "Mr Tendai
Phiri". A part that is an English word stays in lower case.</li>
<li class="check"><b>A second check</b>, written separately, reads the result and refuses it
if an identifier shape is still there.</li>
</ol>

<h2>Its own test sets</h2>
<p>Each test set was written by a separate AI agent that never saw the code, with every
piece of personal data marked. The general set has 41 texts (12 support calls, four of them
lower-case speech-to-text, plus meeting notes, CVs, complaint emails, chat logs, a form, a
CSV and more) and 12 texts with no personal data. The school sets are the ones hush 0.1.0
was built on; set 3 was held out from its tuning.</p>

<h3>Names caught, by what hush is given</h3>
<div class="legend"><span><i style="background:var(--s1)"></i>General set, no config (322 sightings)</span>
<span><i style="background:var(--s2)"></i>School set 3, education config (221 sightings)</span></div>
%(fig1)s
<details><summary>Show the numbers</summary>
<div class="wrap"><table>
<tr><th>Names caught</th><th class="n">patterns only</th><th class="n">+ first-name list</th><th class="n">+ known people</th><th class="n">share preset</th></tr>
<tr><td>General set (41 texts)</td><td class="n">73.6%%</td><td class="n">80.7%%</td><td class="n">86.0%%</td><td class="n">88.8%%</td></tr>
<tr><td>School set 3 (60 texts, held out)</td><td class="n">73.3%%</td><td class="n">82.4%%</td><td class="n">91.0%%</td><td class="n">91.0%%</td></tr>
</table></div>
</details>
<p class="note">The known list is the single largest gain on both sets. In the school set
the known list is the class list, and most names in it are pupils on that list.</p>

<h3>The general set, in detail</h3>
<div class="wrap"><table>
<tr><th>General set, sightings</th><th class="n">patterns only</th><th class="n">share preset</th></tr>
<tr><td>Names on the known list (97)</td><td class="n">71.1%%</td><td class="n">99.0%%</td></tr>
<tr><td>Known people written another way: nicknames, initials, reordered (32)</td><td class="n">50.0%%</td><td class="n">62.5%%</td></tr>
<tr><td>Names not on the known list (193)</td><td class="n">78.8%%</td><td class="n">88.1%%</td></tr>
<tr><td>Names to keep, left whole (89)</td><td class="n">94.4%%</td><td class="n">100%%</td></tr>
<tr><td>Phones, emails, postcodes, dates of birth, cards, bank details, IPs, NI numbers (103)</td><td class="n">100%%</td><td class="n">100%%</td></tr>
<tr><td>Usernames (31)</td><td class="n">64.5%%</td><td class="n">93.5%%</td></tr>
<tr><td>Reference numbers (29)</td><td class="n">89.7%%</td><td class="n">89.7%%</td></tr>
<tr><td>Addresses (28)</td><td class="n">78.6%%</td><td class="n">78.6%%</td></tr>
<tr><td>Texts with no personal data that lost a word (12)</td><td class="n">8</td><td class="n">3</td></tr>
<tr><td>Texts restored exactly by <code>ask-ai</code> (41)</td><td class="n">41</td><td class="n">39</td></tr>
</table></div>
<p class="note">A sighting counts as caught when none of its letters or digits is left in
place; a kept title ("Mrs") does not count as a leak. The two inexact restores hold one name
in two cases of letter, which comes back in the first case seen. The general set is not
fully held out: its first run showed two faults that were then fixed (a kept person lost a
nickname to the known list, and "Mr Szymański" was cut at the "ń"). Kept names went from
91.0%% to 100%% and names overall from 88.2%% to 88.5%%; the public-benchmark work since
moved names to 88.8%% and addresses from 57.1%% to 78.6%%.</p>

<p class="note">The school example: hush 0.1.0 was built for school text, and
<code>examples/education/hush.toml</code> keeps or betters its figures. On the held-out
school set: 91.0%% of pupil names (90.5%% in 0.1.0), 97.8%% of pupils on the class list,
62.2%% of nicknames and initials, 95.9%% of adults, 3 of 25 name-free texts touched.</p>

<h2>What it misses</h2>
<ul>
<li>Nicknames and initials of known people ("Kev", "JK"). Put known nicknames in the known
list's Preferred column.</li>
<li>Names that are also words, mid-sentence ("Mark", "Hope", "Bill") or in lower case with
nothing after them that marks a person ("jade").</li>
<li>Lower-case surnames that are also words ("daniel smith") unless the person is known,
and names in capitals in forms.</li>
<li>Addresses: 79%% on the general set. A town on its own, with no street, stays.</li>
<li>A year on its own stays unless the config asks for years.</li>
<li>Organisation names stay, and a company named like a person may be taken as one. Towns
and places that are first names (Paris, Jordan) may be taken too.</li>
<li>Anything that identifies without a name: "the only engineer on the night shift". It
counts ages, places, jobs, dates and rare details left in a text and warns above a
threshold, but removes none of them.</li>
</ul>

<h2>Before using it on real text</h2>
<ol>
<li>Write a config for your text, starting from the closest example, and pass the known
people and the names to keep. They are the largest gain.</li>
<li>For another country's names, add them under <code>[names] files</code>, or rebuild the
lists from that country's register with <code>tools/build_names.py</code>.</li>
<li>Measure on real text before trusting these numbers: a few hundred real texts, scrubbed,
read by someone your data protection lead trusts, and scored with the bench.</li>
<li>Keep the second check on for anything that leaves your own systems.</li>
</ol>

<h2>Call transcripts</h2>
<p><a href="transcripts-plan.html">transcripts-plan.html</a> sets out the design for call
transcripts between an agent and a customer: keep the two of them, remove every other name,
flag each by the role the words around it give, and use a language model only to judge the
candidates the rules found. Speaker labels, role cues and flags are built; the model pass is
not.</p>

<h2>Try it</h2>
<pre>python3 -m hush presets
python3 -m hush packs
python3 -m hush scrub --config examples/support-call/hush.toml examples/support-call/call.txt
python3 -m hush scrub --config examples/llm-document/hush.toml examples/llm-document/notes.txt
python3 -m unittest discover -s tests
python3 bench/bench.py bench/general/cases.json</pre>
<p class="note">Run from the repository root. Tested on Python 3.14. The README has the
config keys, the Python interface, the known-people format and how to pass a key for
<code>dataset</code> and <code>demo</code>.</p>

<footer>
<p>Code: MIT licence. First names derived from the ONS's "Baby names in England and Wales:
1996 to 2025" under the Open Government Licence v3.0. English words from SCOWL (Debian
<code>wbritish</code>), copyright Kevin Atkinson and others. All names in this page and the
test sets are made up. Public test sets: PII-TRACE (Perplexity, MIT), Nemotron-PII (NVIDIA,
CC BY 4.0), synthetic chat logs (AI Training Data Broker, CC BY 4.0), TAB (Norsk
Regnesentral, MIT); none of their text is in this page.</p>
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
    "demo": esc(DEMO["demo"]), "logs": esc(DEMO["logs"]), "flags": esc(FLAGS),
    "fig0": fig_compare(), "fig1": fig_dots(),
}
page = PAGE.replace("%%", "%")
for name, value in FILL.items():
    page = page.replace("%%(%s)s" % name, value)
assert "%(" not in page
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(page, encoding="utf-8")
print("wrote", OUT, len(page), "bytes")
