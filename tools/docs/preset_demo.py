"""One sentence through each preset, and the support-call example before and after, for
the explainer. Run from the repository root:

    python3 tools/docs/preset_demo.py > preset_demo.json
"""
import json
import sys

sys.path.insert(0, ".")
from hush import Hush, Person  # noqa: E402

known = [Person("Gareth", "Lyle", username="glyle82", role="customer"),
         Person("Grace", "Okafor", role="customer")]
text = ("Gareth Lyle (glyle82) told Ms Pemberton the refund hasn't arrived. "
        "Will you ring grace's mobile on 07700 900481?")
out = {"text": text}
for name in ("ask-ai", "share", "dataset", "demo", "logs"):
    r = Hush(name, people=known, key=b"explainer-example").scrub(text)
    out[name] = r.text
    if name == "ask-ai":
        out["ask-ai-restored"] = r.restore(r.text)

call = open("examples/support-call/call.txt", encoding="utf-8").read()
result = Hush(config="examples/support-call/hush.toml").scrub(call)
out["call_before"] = call
out["call_after"] = result.text
out["call_flags"] = [dict(f, shown=result.text[f["start"]:f["end"]]) for f in result.flags]
print(json.dumps(out, ensure_ascii=False, indent=1))
