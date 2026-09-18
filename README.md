# Jev for Hermes

Use Jev, TypeSafe AI's System One model, for small structured decisions around Hermes Agent. Hermes still plans, reasons, calls tools, runs its guardrails, and requests human approval.

This plugin classifies each user turn, conservatively narrows tool definitions, adds semantic approval requests, and checks coding completion claims against bounded verification evidence. It does **not** route providers or replace the agent model.

## Architecture

```text
User message
    │
    ▼
pre_llm_call → one Jev System One request (3 Choice + 5 Noul questions)
    │
    ▼
Bounded (session_id, turn_id) cache
    ├─ llm_request → optional first-request tool shaping
    ├─ pre_tool_call → read-only bypass or semantic risk assessment
    │                     └─ Hermes human approval, never permission to execute
    └─ post_tool_call → bounded verification evidence
                          └─ pre_verify → optional bounded continuation
                                      │
                                      ▼
                           Hermes agent loop and guardrails
```

## Install

Requires Python 3.11+ and a Hermes checkout exposing `PluginContext.register_hook`, `register_middleware`, `get_config`, `iter_hook_callbacks`, and the hooks below. Tested against Hermes commit `4e06e5f38a`; older releases may lack these contracts. No Hermes core changes are required.

```bash
hermes plugins install robbyczgw-cla/hermes-plugin-jev --no-enable
```

Install the official SDK **using the Python interpreter that runs Hermes**. For example, after activating the Hermes virtual environment:

```bash
python -m pip install 'typesafe-sdk>=0.6.0,<0.7'
```

Hermes does not automatically install a plugin's declared Python dependencies. A missing SDK leaves this plugin inactive, not Hermes broken.

Set `TYPESAFE_API_KEY` using your secret manager or Hermes's protected environment file (`~/.hermes/.env`, mode `0600`). Do not commit it or paste it into command arguments. Obtain an API key from [TypeSafe AI](https://typesafe.ai).

```bash
hermes plugins enable jev-router
hermes jev status
```

Start a new Hermes process after installing or changing settings. For a gateway, use your normal controlled restart procedure; do not restart it from an active turn. Installing this repository does not change the agent model or enable any provider routing.

Disable all behavior:

```bash
hermes plugins disable jev-router
```

The plugin ID is **`jev-router`**, the Python package is **`jev_router`**, and the repository/distribution name is **`hermes-plugin-jev`**. The vendor SDK and environment variable retain their TypeSafe names.

## Configuration

Merge into Hermes's existing `config.yaml`. Settings are read exclusively through `ctx.get_config` under `plugins.entries.jev-router.settings`; no separate configuration file exists.

```yaml
plugins:
  enabled:
    - jev-router
  entries:
    jev-router:
      settings:
        enabled: true
        decision_model: jev-latest
        timeout_seconds: 2.0
        max_workers: 4
        state_max_bytes: 8000
        turn_classifier:
          enabled: true
        tool_shaping:
          enabled: true
          min_confidence: 0.95
        risk_gate:
          enabled: true
          approval_threshold: 0.80
        verify:
          enabled: true
          continue_threshold: 0.85
          max_nudges: 2
        cache:
          max_turns: 256
          ttl_seconds: 1800
        telemetry:
          enabled: true
          max_events: 128
```

`decision_model` selects only the Jev decision model, not the Hermes agent model. The bare key `model` is reserved by Hermes's configuration API and is not used here.

`risk_gate.read_only_tools` optionally replaces the default bypass list: `read_file`, `search_files`, `web_search`, `web_extract`, `web_search_plus`, `web_extract_plus`, `session_search`, `skills_list`, `skill_view`, `tool_search`, and `tool_describe`. Keep it restricted to tools whose semantics you trust. `terminal`, memory mutations, generic API tools, and browser automation are not bypassed. An empty list assesses every tool.

Invalid configuration disables this plugin and logs a fixed warning. Confidence values must be finite; shaping cannot be configured below 0.95. Timeouts are limited to 0.01–10 seconds, cache entries to 4096, state to 16 KB, workers to 16, and local verification nudges to 3. Configure the plugin timeout comfortably below Hermes's hook callback timeout, whose default is 30 seconds: Hermes itself fails closed on timed-out policy hooks.

## Decisions

### Turn classification

One System One request contains three `Choice` questions (`intent`, `complexity`, `side_effect_likelihood`) and five `Noul` yes/no probabilities (`needs_web`, `needs_browser`, `needs_terminal`, `needs_files`, `should_delegate`). Intent choices are chat, coding, research, system administration, automation, data analysis, file work, and other.

The state contains the current user message, platform, and agent model. It never includes the conversation history. Choice confidence is the minimum of the three Choice confidences. Probabilities are model estimates, not calibrated guarantees.

A lock-protected bounded cache uses `(session_id, turn_id)`. Concurrent duplicate classification hooks share one in-flight request; failures are cached too. Classification is never called by `llm_request`. Without a turn ID, a legacy `pre_llm_call` creates a local turn ID; this fallback relies on that hook firing once per turn. Missing session IDs disable behavior. Session-only consumers abstain when more than one unfinished turn exists. Entries expire by TTL, completed entries make room first, and session end clears the session.

### Tool shaping

V0 only narrows **very high-confidence trivial/simple chat**, not arbitrary intent labels. The intent, complexity, side-effect class, and every capability probability must agree. It runs only for the first provider request (`api_call_count == 1`) and before any observed tool call. Later requests get the original tool set.

The pure `shape_tools` function supports OpenAI Chat Completions and Responses function definitions. It returns a new outer request and tool list without modifying the input. Unknown or mixed schemas, built-in provider tools, forced/required tool choices, duplicate names, low confidence, or an empty surviving tool set produce no change. Clarification, task tracking, meta tools, and unknown tools stay available. The middleware cannot add a tool or execute one.

### Additive risk gate

Read-only tools bypass Jev. Eligible calls ask six independent Noul questions in one request: was the action requested, does it change external state, is it destructive, is it hard to reverse, could it expose secrets, and would confirmation be expected?

Python combines those signals. Significant risk or semantic uncertainty can return an `approve` directive. This is a **request for human approval**, not an approval grant. The plugin never returns `allow`, edits tool arguments, executes a tool, or modifies Hermes's policy configuration.

**Current Hermes arbitration constraint:** the first `block` or `approve` hook result wins. This plugin emits `approve` only when its hook is last in Hermes's public callback snapshot. If another hook follows it, Jev abstains rather than shadowing a later block. Earlier block hooks continue to win. Register deterministic policy hooks before this plugin when semantic approvals are wanted. This check is conservative; a later observer also disables Jev approval requests. Hermes plugin registration is expected to remain stable while a turn runs.

### Coding verification

Only Hermes-provided nonempty `changed_paths` enables the check. `post_tool_call` retains at most eight short verification records: tool, sanitized command, explicit exit status, and a bounded output excerpt. Compound shell commands are not accepted as positive evidence. File edits and other terminal commands invalidate earlier evidence; background starts without an exit code are not successful tests.

Four Noul questions assess the completion claim, verification evidence, inconsistency, and need for another iteration. Strong signals can return `continue`; absence of evidence alone is not enough. Each attempt is queried once, with both the plugin's `max_nudges` and Hermes's existing `max_verify_nudges` bounding the loop. Hermes supplies no turn ID to `pre_verify` in the tested checkout, so ambiguous overlapping turns abstain.

## Failure behavior and security

**TypeSafe/Jev decisions are probabilistic semantic signals. They do not replace deterministic authorization or Hermes guardrails.**

Missing credentials/SDK, SDK exceptions, malformed responses, insufficient confidence, timeouts, exhausted worker capacity, unknown payloads, and plugin hook errors leave normal Hermes behavior in place. Existing deterministic blocks remain unchanged. SDK retries are disabled. Daemon workers enforce a caller deadline and have no unbounded queue; a timed-out network request may continue in its worker until transport timeout, but cannot apply a late decision.

Enabling this plugin sends bounded user/task text and selected tool arguments to TypeSafe's hosted API. Consider your data policy before enabling it. The sanitizer removes the configured key, obvious credential fields, bearer/basic credentials, credential-shaped strings, private keys, and URL credentials **before** truncation. It limits depth, fields, string length, and total serialized bytes. Sanitization is best-effort secret minimization, **not** a DLP guarantee; private facts may remain. Disable the plugin for data that must not leave the machine.

SDK wire logs are suppressed only in this plugin's request context, even with SDK DEBUG logging enabled. Telemetry never contains conversations, tool output, arguments, secret values, or exception messages. Logs expose only bounded decision metadata, fallback categories, latency, model ID, and token usage.

`hermes jev status` reports settings, key presence (never value), active state, and process-local telemetry. A separate CLI process cannot report the gateway's in-memory counters. Logs are emitted under `hermes.plugins.jev_router`; in-memory events are bounded by `telemetry.max_events`.

## Develop and test

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check .
ruff format --check .
python -m build
python -m twine check dist/*
```

Unit tests use a fake DecisionEngine. SDK contract tests use the real official SDK with a fake HTTP transport, including secret redaction, no retries, and malformed-response tests. No ordinary test needs a real API key.

Run the official Hermes loader/config/middleware/approval contracts in an isolated temporary Hermes home, using Hermes's Python environment:

```bash
HERMES_SOURCE=/path/to/hermes /path/to/hermes/venv/bin/python -m pytest tests/test_hermes_contract.py -q
```

Also run the affected upstream tests from the Hermes checkout:

```bash
python -m pytest tests/hermes_cli/test_plugins.py tests/agent/test_verify_hooks.py -q
```

### Optional live demo

With the key already in the environment:

```bash
jev-router demo
# or
python -m jev_router.demo
# explicit pytest opt-in
RUN_JEV_LIVE=1 python -m pytest tests/test_live.py -s
```

The demo automatically skips without a key. It classifies four public examples, evaluates a hypothetical build-directory deletion, and assesses a clearly labelled synthetic failed-test scenario. It prints decisions and measured latency. **It never executes the hypothetical commands.** Actual API calls may incur charges. This is a smoke test, not a routing-quality or cost-effectiveness benchmark.

## Limits and next steps

- No provider/model switching, persistent decision database, dashboard, fine-tuning, or agent replacement.
- Initial shaping covers only simple chat and recognized function schemas. High thresholds will often preserve every tool.
- Verification recognizes a small set of direct foreground test/lint/build commands. It cannot prove test relevance or coverage, inspect actual diffs, or follow remote/background jobs to completion.
- Approval emission depends on safe hook ordering; changing hooks concurrently is outside the supported runtime contract.
- A TTL-bounded cache guarantees reuse while an entry is retained, not forever across process restarts or expiration.
- `DecisionEngine` is a small protocol. An adapter benchmark can implement it without changing hooks; `system-one-adapter-python` is not a runtime dependency.

The next useful work is a blinded Jev-versus-adapter benchmark, better evidence collection for silent failures, and delegation recommendations. Same-provider model routing remains out of V0.
