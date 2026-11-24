"""One sentence through each preset, for the explainer."""
import json
import sys

sys.path.insert(0, ".")
from hush import Hush, read_roster

roster = read_roster("examples/class-9X.csv")
text = ("Aisha Khan (akhan23) told Mrs Pemberton she can't log in. "
        "Will is off sick; Will you reset grace's Method Check?")
out = {"text": text}
for name in ("ask-ai", "share", "dataset", "demo", "logs"):
    r = Hush(name, roster=roster, key=b"explainer-example").scrub(text)
    out[name] = r.text if name != "ask-ai" else r.text
    if name == "ask-ai":
        out["ask-ai-restored"] = r.restore(r.text)
print(json.dumps(out, ensure_ascii=False, indent=1))
