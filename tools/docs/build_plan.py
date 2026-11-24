"""Build docs/transcripts-plan.html with the explainer's styles and no scripts.

    python3 build_plan.py docs/explainer.html docs/transcripts-plan.html

The research figures are each cited to a numbered source in the page. The test figures
come from bench/bench.py on bench/general/cases.json with no config."""
import re
import sys
from pathlib import Path

explainer, out = Path(sys.argv[1]), Path(sys.argv[2])
style = re.search(r"<style>.*?</style>", explainer.read_text(encoding="utf-8"), re.S).group(0)

BODY = """
<h1>Names in call transcripts</h1>
<p class="lede">A design for call transcripts between an agent and a customer: keep the two
of them, take out every other person's name, and flag each one by the role the words around
it give.</p>
<p class="byline">Partly built · goes with <a href="explainer.html">explainer.html</a> and
AGENTS.md in this repository</p>

<h2>In short</h2>
<ul>
<li><b>Code finds the names, a model only judges them.</b> Local rules first, a model call
second if an approved route exists, a person last for anything unsure.</li>
<li><b>The known list matters most.</b> On the general test set in this repository, names on
the known list were caught 99%% of the time, against 87%% with the first-name list alone in
any case. A support team already holds the customer's account and its own agents'
names.</li>
<li><b>A model alone misses names.</b> On tutoring dialogues, Gemini 3.1 Pro asked on its own
found 77%% and 39%% of names on two sets; rules proposing candidates with a model ruling on
each reached 98%% [1].</li>
<li><b>Use a contracted route.</b> For example the paid Gemini API or Vertex AI in London,
under Google's data processing terms. Never a free tier.</li>
<li><b>Call it risk reduction, not anonymisation.</b> A scrubbed transcript with its date and
team can still point to "the customer whose son took the kettle back" [19].</li>
</ul>

<h2>What is built</h2>
<div class="wrap"><table>
<tr><th>Part</th><th>State</th></tr>
<tr><td>Speaker labels: <code>Agent:</code>, <code>Speaker 1:</code>, <code>[00:01:02] Priya:</code>, <code>PRIYA (10:02):</code>, WebVTT</td><td>Built (<code>hush/transcripts.py</code>)</td></tr>
<tr><td>Keep the speakers, or give each one placeholder</td><td>Built (<code>[transcript] speakers</code>)</td></tr>
<tr><td>Agent and customer from the call record, per call</td><td>Built (<code>Hush.scrub(text, keep=..., people=...)</code>)</td></tr>
<tr><td>Role cues and a flag for each name they relabel</td><td>Built (<code>[cues]</code>, <code>Result.flags</code>)</td></tr>
<tr><td>Lower-case speech-to-text: names, a surname after them, numbers said as words</td><td>Built</td></tr>
<tr><td>Second check on the output</td><td>Built</td></tr>
<tr><td>Fuzzy matching of known names, two letters out</td><td>Not built</td></tr>
<tr><td>A local candidate model (GLiNER)</td><td>Not built</td></tr>
<tr><td>The model pass and the check on it</td><td>Not built</td></tr>
<tr><td>A review queue for flags</td><td>Not built; the flags are there to feed one</td></tr>
</table></div>
<p class="note">On the 12 support calls in the general test set (four of them lower-case
speech-to-text), the built parts caught 31 of the 34 names that should go with the
<code>share</code> preset and the known list, and left every agent and customer name
whole.</p>

<h2>The pipeline</h2>
<ol class="steps">
<li><b>Keep list</b> from the call record: the agent (from the team's list) and the customer
(from the account), with first names, surnames, "Mr X" forms, preferred names, and the
speakers the transcript labels by name. These stay.</li>
<li><b>Local candidates</b>: the account's other named people (exact, and fuzzy up to two
letters out), the ONS first-name list in any case, the context rules from hush, the
config's own detectors (account and order references), and optionally one Apache-2.0
GLiNER model with a single "person" label at a low threshold [9][10].</li>
<li><b>Redact the sure ones locally</b>: known-list matches and identifiers (emails, phones,
references, card and bank details). Each person gets one stable placeholder across the
whole call: <code>[family 1]</code>, <code>[staff 2]</code>, <code>[person 3]</code>.</li>
<li><b>A model judges the rest.</b> It gets the partly scrubbed text with speaker labels, the
keep list, the config's roles and the numbered candidates, in overlapping windows of about
40 turns. It returns JSON only: per candidate a role and a decision (redact, keep, unsure),
with the quote and its offsets, plus any names it thinks were missed [21].</li>
<li><b>Code checks the model.</b> A quote that does not match its offsets is rejected.
Nothing outside the redactions may change. A "keep" can never overrule a known-list
match.</li>
<li><b>Flag queue.</b> Every name that is not on the keep list is removed. Names with a role,
unsure items, disagreements, fuzzy matches and names that are also words ("Grace", "Will")
go to a person before the transcript is stored or shared.</li>
<li class="check"><b>Second check</b> on the output for identifier shapes, as in hush.</li>
</ol>

<h3>The flag rule</h3>
<p>A name that is not on the keep list is removed. It is <b>flagged with a role</b> when a
cue word the config names sits within four words of it in the same sentence ("my son",
"my manager", "my neighbour"), or the model gives it a role. The roles and their cue words
are the config's <code>[cues]</code>; <code>examples/support-call/hush.toml</code> has
family, staff and third party. A person keeps the first role found for every mention in
the call. Names with no role are removed as <code>[person n]</code> and counted.</p>
<p class="note">For school calls, the education example's config has pupil cues ready to
turn on ("my son", "in Year 9", "her class", "his homework"), so names near them come out as
<code>[pupil n]</code> and flagged. An earlier version of this plan was written for calls
between a support coach and school staff; that case is now one config.</p>

<h2>What the research says</h2>
<div class="wrap"><table>
<tr><th>Finding</th><th>Source</th></tr>
<tr><td>Rules and small models proposing candidates, a local model (Gemma 31B) ruling
redact or keep on each: recall 0.98, F1 0.95 to 0.97 on tutoring dialogues. Zero-shot
Gemini 3.1 Pro: recall 0.77 and 0.39, worse on long dialogues.</td><td>[1] 2026</td></tr>
<tr><td>Frontier models caught every mention of a name repeated 6 to 10 times in only 5 to
46%% of cases.</td><td>[5] 2026</td></tr>
<tr><td>Names that are also ordinary words lose 20 to 40%% recall in LLMs.</td><td>[6] FAccT 2026</td></tr>
<tr><td>GPT-4 on 3,505 student forum posts: recall 0.96, precision 0.53, and it fixed
grammar it was told to leave.</td><td>[3] EDM 2024</td></tr>
<tr><td>Presidio as a name finder over-flags: recall 0.83, precision 0.24 on student
essays.</td><td>[2] JEDM 2025</td></tr>
<tr><td>Maths tutoring: Presidio F1 0.38; maths-aware LLM prompting 0.80 to 0.82. Numbers
get over-redacted, so domain words and numbers need their own handling.</td><td>[7] 2026</td></tr>
<tr><td>Few-shot examples help (GPT-3.5 F1 0.53 to 0.83); a per-candidate verifier raises
precision, not recall.</td><td>[4], [2]</td></tr>
<tr><td>Contact-centre tools (AWS, Azure, Google) redact every name or a listed set. None
tells a customer's family from the agent's colleagues; the pattern is a per-call
allow-list plus a detector.</td><td>[17] [18]</td></tr>
</table></div>
<p class="note">No published benchmark matches this setting (UK customer calls, transcribed
speech). Most of the work above is on education text. Treat these as direction, and measure
on your own transcripts.</p>

<h2>Gemini: terms and cost</h2>
<p>One route, as an example of what to check for any model provider.</p>
<div class="wrap"><table>
<tr><th>Route</th><th>What Google's pages say (read 24 November 2026)</th></tr>
<tr><td>Gemini API, paid</td><td>Prompts not used to improve products; covered by Google's
processor terms; logged for a limited period for abuse checks, in any country, so no UK
residency. UK use must be on the paid tier [11][12].</td></tr>
<tr><td>Gemini API, free or Contributor tier</td><td>Do not use: the free tier is not for UK
use and the Contributor tier trains on your data [11].</td></tr>
<tr><td>Vertex AI, London</td><td>No training without permission, under the Cloud data
processing addendum [22]. Zero retention needs caching and logging turned off and no Search
grounding [13]. London offers <code>gemini-3.5-flash</code> and
<code>gemini-2.5-flash</code>; newer Flash models are EU-region only [14].</td></tr>
</table></div>
<p>Cost: <code>gemini-3.5-flash</code> on Vertex is $1.65 per million input tokens [15]. A
30-minute call is about 4,500 words, roughly 6,000 tokens; with instructions, examples and
overlapping windows, call it 15,000. That is about 2.5 US cents a call, before output.</p>
<p class="note">Google Cloud Sensitive Data Protection's <code>PERSON_NAME</code> detector
runs in London and can exclude a list of names per call, but has no independent accuracy
figures and cannot tell a customer's son from the agent's manager [16]. A third opinion at
most.</p>

<h2>Measure before trusting it</h2>
<ol>
<li>Two people annotate 150 to 300 real transcripts inside the approved environment: every
name mention, its role (customer, family, staff, third party, other) and its type (full
name, first name, nickname, initial, transcription slip, word-name, off the known
list).</li>
<li>Report recall per mention and by type, the share of transcripts leaking any name that
should go, over-redaction (agent and customer names lost), and cost per call.</li>
<li>If 300 annotated mentions show no misses, the miss rate is under 1%% with 95%%
confidence (the rule of three: 3/n). One miss in 300 does not give that bound.</li>
<li>Keep a third of the set unseen while tuning, and report that third.</li>
</ol>

<h2>Risks and limits</h2>
<ul>
<li>Transcription slips spell names in ways no list holds; fuzzy matching and the model
help, a person catches the rest.</li>
<li>Nicknames and initials stay the weakest case: about six in ten on the test sets in this
repository.</li>
<li>Context identifies without names. Limit who can read scrubbed transcripts, keep
retention short, and keep the account and date apart from the text where you can.</li>
<li>Calls can mention children and health. Check with the data protection lead what the
contracts allow, and whether the account's other named people may be used as a known
list.</li>
<li>Gemini prices on the API page change on 1 January 2027 [12].</li>
</ul>

<h2>Sources</h2>
<ol class="note">
<li>Zhang H. et al. (2026) Redact or Keep? A fully local AI cascade for educational dialogue de-identification. arXiv:2606.18372</li>
<li>Ji Z., Shen Y., Lin J., Koedinger K. (2025) Enhancing the de-identification of PII in educational data. JEDM 17(2). arXiv:2501.09765</li>
<li>Singhal S. et al. (2024) De-identifying student PII with GPT-4. EDM 2024 short papers</li>
<li>Kuo R. et al. (2025) Benchmarking transformer-based models for medical record de-identification. iScience 28(12)</li>
<li>Zhang K. et al. (2026) PII-TRACE. arXiv:2609.22200</li>
<li>Pham D. et al. (2026) Can large language models really recognize your name? FAccT 2026. arXiv:2505.14549</li>
<li>Zhou Z. et al. (2026) MathEd-PII. arXiv:2602.16571</li>
<li>Kaplan M. (2020) May I ask who's calling? W-NUT 2020</li>
<li>Presidio repository, MIT licence: github.com/data-privacy-stack/presidio</li>
<li>GLiNER PII model cards on Hugging Face (urchade, knowledgator, fastino: Apache-2.0; nvidia: own licence; gliner_base and Piiranha: non-commercial)</li>
<li>Gemini API Additional Terms, effective 23 March 2026: ai.google.dev/gemini-api/terms</li>
<li>Gemini API pricing and logs policy: ai.google.dev/gemini-api/docs/pricing</li>
<li>Vertex AI zero data retention (updated 20 November 2026)</li>
<li>Vertex AI data residency (updated 20 November 2026)</li>
<li>Vertex AI generative AI pricing</li>
<li>Sensitive Data Protection: infoType reference, inspection rules, pricing, locations</li>
<li>Google CX Insights, importing conversations</li>
<li>AWS Transcribe PII redaction; Azure Language PII redaction</li>
<li>ICO anonymisation guidance, effective anonymisation and pseudonymisation (28 March 2025, under review)</li>
<li>ICO, the Children's code and education technologies (30 May 2023)</li>
<li>Gemini structured output: ai.google.dev/gemini-api/docs/structured-output</li>
<li>Google Cloud Data Processing Addendum (30 October 2026)</li>
</ol>
"""

page = ("<!doctype html>\n<html lang=\"en-GB\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Names in call transcripts</title>\n" + style +
        "\n</head>\n<body>\n<main>\n" + BODY.replace("%%", "%") +
        "\n<footer><p>All names in examples are made up. Research run 24 November 2026; "
        "every figure was re-read in its primary source.</p></footer>\n</main>\n</body>\n</html>\n")
assert "<script" not in page.lower()
out.write_text(page, encoding="utf-8")
print("wrote", out, len(page), "bytes")
