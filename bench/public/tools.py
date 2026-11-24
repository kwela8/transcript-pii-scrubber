"""The tools under test. make(name) builds one once and returns spans(text), which gives
([(start, end, label, score), ...], extra) in the original text's offsets.

To test a newer hush, point HUSH_DIR at its unpacked copy; hush_spans is the only place
that calls it.
"""
import difflib
import os
import pathlib
import re
import sys

# The working folder (models/ lives here) and the hush under test: this repo unless
# HUSH_DIR names an unpacked copy of another version.
ROOT = pathlib.Path(os.environ.get("BENCH_DIR", ".")).resolve()
HUSH_DIR = os.environ.get("HUSH_DIR",
                          str(pathlib.Path(__file__).resolve().parent.parent.parent))
GLINER_MODEL = os.environ.get("GLINER_MODEL", str(ROOT / "models" / "gliner-pii-large-v1.0"))
GLINER_THRESHOLD = 0.3      # the model card's recommended starting point
THREADS = 4


# --- hush ---------------------------------------------------------------------
def hush_spans(text, config, _cache={}):
    """(a) "core": hush.core.scrub, the capitalised-name guess on, no lists.
    (b) "share": the share preset with no class list (first-name list on, any case).
    Returns the spans hush replaced, found by lining its token output up with the input."""
    if not _cache:
        sys.path.insert(0, HUSH_DIR)
        from hush import Hush, core
        _cache.update(core=core, share=Hush("share"))
    core = _cache["core"]
    if config == "core":
        tokens, mapping = core.scrub(text)
        extra = {}
    else:
        result = _cache["share"].scrub(text)
        tokens, mapping = result.tokens, result.mapping
        extra = {"refused": result.refused, "findings": sorted(result.findings)}
    spans, extra["aligned"] = align(text, tokens, mapping.by_token, core.TOKEN)
    return spans, extra


def align(text, tokens, real, token_re):
    """Walk the token text: what lies between tokens is the input, unchanged, and each
    token stands for len(real[token]) input characters. If the rebuilt text is not the
    input exactly, fall back to a diff. Returns (spans, how)."""
    spans, rebuilt, same, i, j = [], [], True, 0, 0
    for m in token_re.finditer(tokens):
        value = real.get(m.group(0))
        if value is None:
            continue
        i += m.start() - j
        spans.append((i, i + len(value), m.group("kind"), None))
        rebuilt += [tokens[j:m.start()], text[i:i + len(value)]]
        same = same and text[i:i + len(value)].casefold() == value.casefold()
        i, j = i + len(value), m.end()
    rebuilt.append(tokens[j:])
    if same and "".join(rebuilt) == text:
        return spans, "walk"
    return diff_spans(text, tokens, token_re), "diff"


def diff_spans(text, tokens, token_re):
    """Fallback: each token becomes one private-use mark and difflib lines the texts up."""
    kinds = [m.group("kind") for m in token_re.finditer(tokens)]
    flat = token_re.sub("\ue000", tokens)
    marks = [i for i, ch in enumerate(flat) if ch == "\ue000"]
    kind_at = dict(zip(marks, kinds))
    spans = []
    matcher = difflib.SequenceMatcher(None, text, flat, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete") and i2 > i1:
            found = [kind_at[j] for j in range(j1, j2) if j in kind_at]
            spans.append((i1, i2, found[0] if found else "DIFF", None))
    return spans


# --- Presidio -----------------------------------------------------------------
def make_presidio():
    from presidio_analyzer import AnalyzerEngine
    engine = AnalyzerEngine()          # default: spaCy en_core_web_lg, every default recogniser

    def spans(text):
        found = engine.analyze(text=text, language="en")    # default score_threshold 0
        return [(r.start, r.end, r.entity_type, round(r.score, 3)) for r in found], {}
    return spans


# --- GLiNER -------------------------------------------------------------------
_WORD = re.compile(r"\w+(?:[-_]\w+)*|\S")      # GLiNER's own whitespace word splitter


def chunks(text, limit=300):
    """Cut text into pieces of at most `limit` GLiNER words, at a line or sentence end
    where one is near, so no entity is cut in half if it can be helped."""
    words = [m.span() for m in _WORD.finditer(text)]
    start_word = 0
    while start_word < len(words):
        end_word = min(start_word + limit, len(words))
        if end_word < len(words):
            for k in range(end_word - 1, start_word + limit // 2, -1):
                gap = text[words[k][1]:words[k + 1][0]]
                if "\n" in gap or text[words[k][0]:words[k][1]] in (".", "?", "!"):
                    end_word = k + 1
                    break
        a, b = words[start_word][0], words[end_word - 1][1]
        yield a, text[a:b]
        start_word = end_word


def make_gliner(short=False):
    import torch
    torch.set_num_threads(THREADS)
    from gliner import GLiNER
    from labels import GLINER, GLINER_SHORT
    model = GLiNER.from_pretrained(GLINER_MODEL, local_files_only=True)
    model.eval()
    asked = list(GLINER_SHORT if short else GLINER)

    def spans(text):
        out = []
        pieces = list(chunks(text))
        with torch.no_grad():
            found = model.inference([p for _, p in pieces], asked,
                                    threshold=GLINER_THRESHOLD, batch_size=8)
        for (offset, _), entities in zip(pieces, found):
            out += [(offset + e["start"], offset + e["end"], e["label"], round(e["score"], 3))
                    for e in entities]
        return out, {}
    return spans


def make(name):
    if name == "hush-core":
        return lambda text: hush_spans(text, "core")
    if name == "hush-share":
        return lambda text: hush_spans(text, "share")
    if name == "presidio":
        return make_presidio()
    if name == "gliner":
        return make_gliner()
    if name == "gliner-short":
        return make_gliner(short=True)
    raise SystemExit("unknown tool %r" % name)


def version(name):
    if name.startswith("hush"):
        sys.path.insert(0, HUSH_DIR)
        import hush
        return "hush %s from %s" % (hush.__version__, HUSH_DIR)
    if name == "presidio":
        from importlib.metadata import version as v
        return "presidio-analyzer %s, spacy %s, en_core_web_lg %s" % (
            v("presidio-analyzer"), v("spacy"), v("en-core-web-lg"))
    from importlib.metadata import version as v
    return "gliner %s, torch %s, model %s, threshold %s, %s labels" % (
        v("gliner"), v("torch"), pathlib.Path(GLINER_MODEL).name, GLINER_THRESHOLD,
        "10 short" if name == "gliner-short" else "30")
