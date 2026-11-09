"""What the staff member reads on a plan card: each held tool call as a title and its arguments, plus the outcome once run."""
import json

from app.models import AssistantPlan
from app.services.assistant.engine import call_args
from app.services.assistant.tools import LANGS, TOOLS

MAX_VALUE = 400


def title(name: str) -> str:
    """The first sentence of the tool's description, or the name spelled out."""
    tool = TOOLS.get(name)
    if tool is None:
        return name.replace("_", " ")
    first = tool.description.split(". ")[0].strip().rstrip(".")
    return first if len(first) <= 90 else first[:88].rstrip() + "…"


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int | float):
        return f"{v:g}" if isinstance(v, float) else str(v)
    s = str(v)
    return s if len(s) <= MAX_VALUE else s[:MAX_VALUE - 1] + "…"


def rows(args: dict) -> list[dict]:
    """[{key, value, lines?}] — multilingual dicts show one line per language; lists and other dicts as compact JSON."""
    out = []
    for k, v in args.items():
        if v is None or v == "" or v == {} or v == []:
            continue
        if isinstance(v, dict) and v and all(lang in LANGS for lang in v):
            out.append({"key": k, "lines": [(lang, _scalar(v[lang])) for lang in LANGS if v.get(lang) not in (None, "")]})
        elif isinstance(v, list) and all(isinstance(x, str | int | float | bool) for x in v):
            out.append({"key": k, "value": ", ".join(_scalar(x) for x in v)})
        elif isinstance(v, dict | list):
            out.append({"key": k, "value": _scalar(json.dumps(v, ensure_ascii=False))})
        else:
            out.append({"key": k, "value": _scalar(v)})
    return out


def view(plan: AssistantPlan) -> list[dict]:
    """One entry per held call: id, name, title, argument rows, and after the run its action or error."""
    by_call = {r.get("call_id"): r for r in plan.results or []}
    by_action = {a.id: a for a in plan.actions}
    out = []
    for call in plan.calls:
        fn = call.get("function") or {}
        name = fn.get("name") or ""
        args = call_args(call) or {}
        res = by_call.get(call.get("id"))
        out.append({"id": call.get("id"), "name": name, "title": title(name), "rows": rows(args), "result": res,
                    "action": by_action.get((res or {}).get("action_id")), "error": (res or {}).get("error")})
    return out
