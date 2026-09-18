"""Pure, copy-on-write shaping. V0 narrows only clear, simple chat."""

import math

ELIGIBLE = frozenset(
    {
        "terminal",
        "read_file",
        "write_file",
        "patch",
        "search_files",
        "web_search",
        "web_extract",
        "web_search_plus",
        "web_extract_plus",
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_press_key",
    }
)


def shape_tools(request, decision, min_confidence=0.95):
    if not isinstance(request, dict) or decision is None:
        return None
    if (
        decision.intent != "chat"
        or decision.complexity not in ("trivial", "simple")
        or decision.side_effect_likelihood != "low"
    ):
        return None
    probabilities = [
        decision.confidence,
        decision.needs_web,
        decision.needs_browser,
        decision.needs_terminal,
        decision.needs_files,
        decision.should_delegate,
    ]
    if any(
        type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1
        for p in probabilities
    ):
        return None
    if decision.confidence < min_confidence or max(probabilities[1:]) > 1 - min_confidence:
        return None
    choice = request.get("tool_choice")
    if choice is not None and choice not in ("auto", "none"):
        return None
    tools = request.get("tools")
    if not isinstance(tools, list) or not tools:
        return None
    names = []
    formats = set()
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            return None
        if isinstance(tool.get("function"), dict):
            f = tool["function"]
            formats.add("chat")
        elif "name" in tool and "parameters" in tool:
            f = tool
            formats.add("responses")
        else:
            return None
        if not isinstance(f.get("name"), str) or not isinstance(f.get("parameters"), dict):
            return None
        names.append(f["name"])
    if len(formats) != 1 or len(names) != len(set(names)):
        return None
    kept = [t for t, n in zip(tools, names) if n not in ELIGIBLE]
    # Keep at least one tool to avoid invalid required/tool config combinations.
    if not kept or len(kept) == len(tools):
        return None
    return dict(request, tools=kept)
