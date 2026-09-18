"""Local-only context guards; never send conversation history to Jev."""

import re

# Deliberately narrow until real workloads have been evaluated. A high Jev
# confidence cannot establish that a short reply is an independent request.
STANDALONE_CHAT = frozenset(
    {
        "hello",
        "hi",
        "hey",
        "good morning",
        "good evening",
        "hallo",
        "guten morgen",
        "guten abend",
        "how are you",
        "wie geht es dir",
    }
)


def standalone_chat(text):
    return isinstance(text, str) and re.sub(r"[.!?]+$", "", text.strip().lower()) in STANDALONE_CHAT


def ambiguous_followup(text):
    """Known references have no standalone action scope; false positives ask a human."""
    if not isinstance(text, str) or not text.strip():
        return True
    normalized = " ".join(re.sub(r"[.!?,]+", " ", text.lower()).split())
    return bool(
        re.match(
            r"^(?:yes|yep|yeah|ok|okay|continue|proceed|resume|ja|weiter|weitermachen)\b",
            normalized,
        )
        or re.fullmatch(
            r"(?:(?:please|bitte)\s+)?(?:do|fix|run|change|delete|mach|ändere|lösche)"
            r"\s+(?:it|that|this|them|das|dies)",
            normalized,
        )
        or re.fullmatch(r"(?:run|do) (?:the )?(?:tests?|checks?) (?:too|again)", normalized)
        or normalized
        in {
            "it",
            "that",
            "this",
            "those",
            "them",
            "again",
            "too",
            "das",
            "dies",
            "nochmal",
            "ebenso",
        }
    )


def shaping_guard(request, state):
    if state.get("input_metadata", {}).get("input_complete") is not True:
        return False, "incomplete_input"
    context = state.get("conversation")
    if not isinstance(context, dict) or context.get("prior_turn_seen") is not False:
        return False, "prior_or_unknown_context"
    if not standalone_chat(state.get("user_message")):
        return False, "followup_or_task"
    if (
        not isinstance(request, dict)
        or request.get("previous_response_id")
        or request.get("conversation")
    ):
        return False, "unknown_context"
    # Mixed APIs, multimodal input, compaction summaries, or any prior turn are
    # not evidence of a fresh conversation. Unsupported formats keep all tools.
    if "messages" in request and "input" in request:
        return False, "unknown_context"
    messages = request.get("messages", request.get("input"))
    if not isinstance(messages, list) or not messages or len(messages) > 32:
        return False, "unknown_context"
    users = []
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("tool_calls")
            or message.get("function_call")
        ):
            return False, "ongoing_tool_workflow"
        role = message.get("role")
        if role in ("system", "developer"):
            continue
        if role != "user" or not isinstance(message.get("content"), str):
            return False, "prior_or_unknown_context"
        users.append(message["content"])
    if len(users) != 1 or users[0] != state.get("user_message"):
        return False, "prior_or_unknown_context"
    return True, "fresh_standalone_chat"
