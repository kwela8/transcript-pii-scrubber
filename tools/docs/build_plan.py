"""Build docs/transcripts-plan.html with the explainer's styles and no scripts.

    python3 build_plan.py docs/explainer.html docs/transcripts-plan.html

The research figures are each cited to a numbered source in the page. The test figures
come from bench/student_bench.py on bench/student_cases_3.json."""
import re
import sys
from pathlib import Path

explainer, out = Path(sys.argv[1]), Path(sys.argv[2])
style = re.search(r"<style>.*?</style>", explainer.read_text(encoding="utf-8"), re.S).group(0)

BODY = """
<h1>Pupil names in call transcripts</h1>
<p class="lede">A plan for customer call transcripts between a support coach and school
staff: take out every person's name that is not a known speaker's, and flag the ones that
look like pupils.</p>
<p class="byline">A design, not yet built · goes with <a href="explainer.html">explainer.html</a>
and AGENTS.md in this repository</p>

<h2>In short</h2>
<ul>
<li><b>Code finds the names, the model only judges them.</b> Local rules first, a Gemini call
second, a person last for anything unsure.</li>
<li><b>The school's class list matters most.</b> On the held-out test set in this repository,
pupils on it were caught 97%% of the time, against 84%% with the first-name list alone in any
case. The provider already holds each school's roll.</li>
<li><b>A model alone misses names.</b> On tutoring dialogues, Gemini 3.1 Pro asked on its own
found 77%% and 39%% of names on two sets; rules proposing candidates with a model ruling on
each reached 98%% [1].</li>
<li><b>Use a contracted route.</b> The paid Gemini API or Vertex AI in London, under
Google's data processing terms. Never the free tier.</li>
<li><b>Call it risk reduction, not anonymisation.</b> A scrubbed transcript with its school
and date can still point to "the Year 9 boy who broke his arm" [19].</li>
</ul>

<h2>The pipeline</h2>
<ol class="steps">
<li><b>Protect list</b> from the call's metadata: the known speakers (the coach and the
member of school staff) with their first names, surnames, "Mrs X" forms, initials and likely
transcription spellings. These stay.</li>
<li><b>Local candidates</b>: the customer school's class list (exact, and fuzzy up to two
letters out), the ONS first-name list in any case, the context rules from hush, and
optionally one Apache-2.0 GLiNER model with a single "person" label at a low threshold
[9][10].</li>
<li><b>Redact the sure ones locally</b>: exact class-list matches and identifiers (UPN, ULN,
emails, phones). Each person gets one stable placeholder, <code>[PUPIL_1]</code>.</li>
<li><b>Gemini judges the rest.</b> It gets the partly scrubbed text with speaker labels, the
protect list and the numbered candidates, in overlapping windows of about 40 turns. It
returns JSON only: per candidate a role (pupil, staff, parent, other) and a decision
(redact, keep, unsure), with the quote and its offsets, plus any names it thinks were
missed [21].</li>
<li><b>Code checks the model.</b> A quote that does not match its offsets is rejected.
Nothing outside the redactions may change. A "keep" can never overrule a class-list
match.</li>
<li><b>Flag queue.</b> Every name that is not a known speaker's is removed. Unsure
items, disagreements, fuzzy matches and names that are also words ("Grace", "Will") go to a
person before the transcript is stored or shared.</li>
<li class="check"><b>Second check</b> on the output for identifier shapes, as in hush.</li>
</ol>

<h3>The flag rule</h3>
<p>A name is flagged <b>likely pupil</b> when it is not on the protect list and any of these
hold: it is on the class list; the model says pupil; or it sits near pupil words ("my son",
"in Year 9", "her class", "his homework", "the kids"). Other names (another teacher, a
parent, a colleague at the provider) are removed too, labelled by role, but not flagged as
pupils.</p>

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
get over-redacted.</td><td>[7] 2026</td></tr>
<tr><td>Few-shot examples help (GPT-3.5 F1 0.53 to 0.83); a per-candidate verifier raises
precision, not recall.</td><td>[4], [2]</td></tr>
<tr><td>Contact-centre tools (AWS, Azure, Google) redact every name or a listed set. None
tells pupils from teachers; the pattern is a per-call allow-list plus a detector.</td><td>[17] [18]</td></tr>
</table></div>
<p class="note">No published benchmark matches this setting (UK school calls, transcribed
speech). Treat these as direction, and measure on the provider's own transcripts.</p>

<h2>Gemini: terms and cost</h2>
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
overlapping windows, call it 15,000. That is about 2.5 US cents a call, before output, which
is small.</p>
<p class="note">Google Cloud Sensitive Data Protection's <code>PERSON_NAME</code> detector
runs in London and can exclude a list of names per call, but has no independent accuracy
figures and cannot tell a pupil from a teacher [16]. A third opinion at most.</p>

<h2>Measure before trusting it</h2>
<ol>
<li>Two people annotate 150 to 300 real transcripts inside the provider's approved environment:
every pupil-name mention, its type (full name, first name, nickname, initial, transcription
slip, word-name, off the class list).</li>
<li>Report recall per mention and by type, the share of transcripts leaking any pupil name,
over-redaction, and cost per call.</li>
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
retention short, and keep the school and date apart from the text where you can.</li>
<li>Whether the class list may be used for this depends on the school contracts; check with
the data protection lead.</li>
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
        "<title>Pupil names in call transcripts: a plan</title>\n" + style +
        "\n</head>\n<body>\n<main>\n" + BODY.replace("%%", "%") +
        "\n<footer><p>All names in examples are made up. Research run 24 November 2026; "
        "every figure was re-read in its primary source.</p></footer>\n</main>\n</body>\n</html>\n")
assert "<script" not in page.lower()
out.write_text(page, encoding="utf-8")
print("wrote", out, len(page), "bytes")
