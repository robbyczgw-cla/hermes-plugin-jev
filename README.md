# Jev for Hermes

Use Jev, TypeSafe AI's System One model, for small structured decisions around Hermes Agent. Hermes still plans, reasons, calls tools, runs its guardrails, and requests human approval.

This plugin classifies each user turn and can request semantic risk approvals, check coding completion claims, and narrow tool definitions. It starts in **shadow mode**: decisions are computed but cannot change tools, approval behavior, or completion. Verification and tool shaping are off by default. It does **not** route providers or replace the agent model.

**Release scope:** preview/beta, with shadow defaults. Risk enforcement, verification, and tool shaping are experimental opt-ins, not a general authorization boundary. Long or incomplete prompts can cause repeated approval requests in enforce mode and suppress verification nudges; evaluate those paths on your workloads before enabling them.

**Before enabling:** this plugin sends selected task text to TypeSafe's hosted API. Read [Privacy and data flow](PRIVACY.md). Plugin code is [MIT-licensed](LICENSE); [SDK licenses and hosted-service terms](THIRD_PARTY.md) are separate.

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
    ├─ tool_request → bounded risk assessment, single-use proposal cache
    │    └─ pre_tool_call → cache only → Hermes human approval
    └─ post_tool_call → bounded verification evidence
                          └─ pre_verify → optional bounded continuation
                                      │
                                      ▼
                           Hermes agent loop and guardrails
```

## Install

Requires Python 3.11+ and a Hermes checkout exposing `PluginContext.register_hook`, `register_middleware`, `get_config`, `iter_hook_callbacks`, and the hooks below. Tested against Hermes commits `4e06e5f38a` and `77ecc72bcdd5da0163cca21c8af0e95b26ba3426`; older releases may lack these contracts. No Hermes core changes are required.

```bash
hermes plugins install robbyczgw-cla/hermes-plugin-jev --no-enable
```

Hermes versions with automatic plugin dependency installation install the declared SDK during plugin installation or enablement. This includes the tested upstream commit `77ecc72bcdd5da0163cca21c8af0e95b26ba3426`.

On older versions such as the tested `4e06e5f38a`, or when installing with `--no-deps` on versions that support it, install the official SDK **using the Python interpreter that runs Hermes**. For example, after activating the Hermes virtual environment:

```bash
python -m pip install 'typesafe-sdk>=0.6.0,<0.7'
```

A missing SDK leaves this plugin inactive, not Hermes broken. Check dependency-installation warnings before enabling it.

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
        mode: shadow
        decision_model: jev-latest
        timeout_seconds: 2.0
        max_workers: 4
        state_max_bytes: 8000
        turn_classifier:
          enabled: true
        tool_shaping:
          enabled: false
          min_confidence: 0.95
        risk_gate:
          enabled: true
          block_unbindable: false
          approval_threshold: 0.80
        verify:
          enabled: false
          continue_threshold: 0.85
          max_nudges: 2
        cache:
          max_turns: 256
          ttl_seconds: 1800
        telemetry:
          enabled: true
          max_events: 128
```

### Recommended rollout

1. **Shadow:** start with the settings above (`mode: shadow`). Eligible enabled stages compute and log decisions; no tool removal, human-approval proposal, deterministic Jev block, or verification continuation can reach Hermes. This still sends data to TypeSafe and adds bounded latency. Enable `verify` or `tool_shaping` while staying in shadow only to observe those stages.
2. **Risk only:** after reviewing representative shadow runs, set `mode: enforce`, keep `risk_gate.enabled: true`, and leave `tool_shaping.enabled` and `verify.enabled` false. Hermes remains the authority for execution.
3. **Optional verification:** enable `verify` after checking false-nudge rates. Incomplete completion input never produces a nudge.
4. **Tool shaping last:** enable it only after workload evaluation shows no false tool removals. The first release deliberately supports a narrow fresh-greeting case, not general conversational tool prediction.

`mode` accepts only `shadow` or `enforce`. Invalid values disable the plugin. Existing installations without a mode setting now become shadow-only; explicitly choose `enforce` to retain behavioral intervention. The [example configuration](examples/config.shadow.yaml) is a merge snippet, not a replacement for your Hermes config. No gateway changes happen automatically.

`decision_model` selects only the Jev decision model, not the Hermes agent model. The bare key `model` is reserved by Hermes's configuration API and is not used here.

`risk_gate.read_only_tools` optionally replaces the default bypass list: `read_file`, `search_files`, `web_search`, `web_extract`, `web_search_plus`, `web_extract_plus`, `session_search`, `skills_list`, `skill_view`, `tool_search`, and `tool_describe`. Keep it restricted to tools whose semantics you trust. `terminal`, memory mutations, generic API tools, and browser automation are not bypassed. An empty list assesses every tool.

Invalid configuration disables this plugin and logs a fixed warning. Confidence values must be finite; shaping cannot be configured below 0.95. Timeouts are limited to 0.01–10 seconds, cache entries to 4096, state to 16 KB, workers to 16, and local verification nudges to 3. Risk requests run in `tool_request` middleware, outside Hermes's fail-closed policy hook. `pre_tool_call` only reads a prepared proposal: it performs no network calls, waits for no cache lock, and emits no logs.

## Decisions

### Turn classification

One System One request contains three `Choice` questions (`intent`, `complexity`, `side_effect_likelihood`) and five `Noul` yes/no probabilities (`needs_web`, `needs_browser`, `needs_terminal`, `needs_files`, `should_delegate`). Intent choices are chat, coding, research, system administration, automation, data analysis, file work, and other.

The state contains the current user message, platform, agent model, and boolean context summaries (prior cached turn, unresolved turn, observed tool workflow). It does not upload conversation history. The shaping guard separately inspects the local provider-request history; missing or ambiguous history preserves every tool. Choice confidence is the minimum of the three Choice confidences. Probabilities are model estimates, not calibrated guarantees.

A lock-protected bounded cache uses `(session_id, turn_id)`. Concurrent duplicate classification hooks share one in-flight request; failures are cached too. Classification is never called by `llm_request`. Without a turn ID, a legacy `pre_llm_call` creates a local turn ID; this fallback relies on that hook firing once per turn. Missing session IDs disable behavior. Session-only consumers abstain when more than one unfinished turn exists. Entries expire by TTL, completed entries make room first, and session end clears the session.

### Tool shaping

Tool shaping is opt-in and only applies in `mode: enforce`. A deterministic guard first requires complete input, a recognized standalone greeting, no cached prior turn, and a complete provider request containing exactly the matching user message (plus optional system/developer messages). An explicit host `is_first_turn: false` also prevents shaping after cache expiry or resume. History, tool/function events, follow-up references, confirmations such as “yes, do it”, unknown message formats, mismatched content, or provider-side conversation state preserve all tools. Cached prior turns remain conservative even when marked complete; expiry cannot bypass the separate provider-history check.

Only then may a **very high-confidence trivial/simple-chat** decision narrow tools. Intent, complexity, side effects, and every capability probability must agree. It runs only for the first provider request (`api_call_count == 1`) and before any observed tool call. Later requests get the original tool set. This restriction trades away most shaping opportunities rather than guessing task resolution from a short follow-up.

The pure `shape_tools` function supports OpenAI Chat Completions and Responses function definitions. It returns a new outer request and tool list without modifying the input. Unknown or mixed schemas, built-in provider tools, forced/required tool choices, duplicate names, low confidence, or an empty surviving tool set produce no change. Clarification, task tracking, meta tools, and unknown tools stay available. The middleware cannot add a tool or execute one.

### Additive risk gate

Read-only tools bypass Jev. In interactive CLI or attended gateway contexts, `tool_request` asks six independent Noul questions in one request: was the action requested, does it change external state, is it destructive, is it hard to reverse, could it expose secrets, and would confirmation be expected?

The middleware does not change arguments. It prepares a single-use proposal bound to the session, turn, tool-call ID, tool name, and full argument digest. The policy hook consumes only an exact match. Missing IDs, changed arguments, expiry (10 seconds), capacity eviction, and cache contention cause abstention. The proposal cache holds at most `cache.max_turns` proposals. No network request runs inside the policy hook; a slow Jev request cannot occupy that hook while another session needs it.

Cron, single-query (`-q`), API-server/webhook sessions, and bare noninteractive scripts do not get Jev approval requests. The plugin uses Hermes's context-local approval predicates, checks again before emission, and abstains if those host APIs are unavailable. Unattended skips record metadata-only telemetry. This does not change Hermes's own cron/unattended approval settings or deterministic guards.

Python combines those signals. In enforce mode, significant risk, semantic uncertainty, incomplete decision input, or a recognized context-dependent follow-up can request human approval. References such as “continue”, “fix that”, or “run the tests too” do not establish action scope on their own. This guard matches leading confirmations and short standalone references, not every occurrence of “this” or “it” in an ordinary task. It can still cause extra prompts; it is not a complete language-understanding layer. Incomplete input cannot be made safe by a low-risk Jev answer, and still requests approval if the semantic request fails. Known ambiguous follow-ups receive the same conservative treatment. This uses an `approve` directive. This is a **request for human approval**, not an approval grant. The plugin never returns `allow`, edits tool arguments, executes a tool, or modifies Hermes's policy configuration. Approval messages name the risk dimensions and show a bounded, sanitized action summary. Explicit `rule_key` values separate tool, risk dimensions, and the sanitized action digest, instead of creating a tool-wide permanent allowlist entry. Incomplete or ambiguous inputs use a fresh one-off rule key rather than an excerpt-based reusable key, so a remembered approval cannot cover a different hidden tail. The prompt asks the user to inspect the full original call, deny if unavailable, and not use “Always” for that request. These keys do not replace deterministic scope checks.

**Current Hermes arbitration constraint:** the first `block` or `approve` hook result wins. This plugin emits `approve` only when its hook is last in Hermes's public callback snapshot. If another hook follows it, Jev abstains rather than shadowing a later block. Earlier block hooks continue to win. Register deterministic policy hooks before this plugin when semantic approvals are wanted. This check is conservative; a later observer also disables Jev approval requests. Hermes plugin registration is expected to remain stable while a turn runs.

For arguments that cannot be safely digested (including the 65,536-character serialized digest limit), Jev abstains by default and records `unbound_input`; native Hermes policy still applies. Large file writes therefore remain available. This abstention is not a safety assessment: Jev cannot protect an action it cannot bind. Set `risk_gate.block_unbindable: true` to require a narrower action instead; attended enforce mode then prepares a `block`, never an approval. Shadow mode creates neither approval nor block proposals.

### Coding verification

Verification is off by default. When enabled, only Hermes-provided nonempty `changed_paths` enables the check. `post_tool_call` retains at most eight short verification observations: tool, sanitized command, explicit exit status, and a bounded output excerpt. Compound/background shell commands, collection-only runs, and help/version/dry-run invocations do not count as successful verification. Observed mutations invalidate earlier records.

Hermes can skip observer hooks, so a missing mutation event cannot prove that an earlier pass is still current. All retained evidence is labelled `freshness: unverified`; historical passes become `observed_success: true`, not current `success: true`. They cannot deterministically suppress a continuation. Jev still needs strong inconsistency and unfinished-work signals to nudge; unknown freshness alone does not trigger another iteration. This conservative policy can cause an extra check after genuinely successful tests.

Four Noul questions assess the completion claim, verification evidence, inconsistency, and need for another iteration. Strong signals can return `continue`; absence of evidence alone is not enough. Each attempt is queried once, with both the plugin's `max_nudges` and Hermes's existing `max_verify_nudges` bounding the loop. Results arriving after turn/session end are discarded. Output excerpts allow up to 1,800 characters; longer output, final responses, or an exhausted state budget still suppress nudges. Telemetry completeness flags must be checked before using shadow observations to judge model quality. Hermes supplies no turn ID to `pre_verify` in the tested checkout, so ambiguous overlapping turns abstain.

## Failure behavior and security

**TypeSafe/Jev decisions are probabilistic semantic signals. They do not replace deterministic authorization or Hermes guardrails.**

Missing credentials/SDK, insufficient confidence, timeouts, malformed responses, and exhausted workers normally leave Hermes behavior in place. There is one conservative exception in the attended enforce-mode risk gate: incomplete input or a recognized ambiguous follow-up requests human approval even when the semantic call fails; unbindable arguments abstain unless `risk_gate.block_unbindable` is explicitly enabled. Unknown shaping payloads and incomplete verification input always abstain. Unexpected plugin-hook errors fall back to Hermes. Existing deterministic blocks remain unchanged. SDK retries are disabled. Daemon workers enforce a caller deadline and have no unbounded queue; a timed-out network request may continue in its worker until transport timeout, but cannot apply a late decision.

Enabling this plugin sends bounded user/task text and selected tool arguments to TypeSafe's hosted API. Consider your data policy before enabling it. The sanitizer removes the configured key, obvious credential fields, bearer/basic credentials, credential-shaped strings, private keys, and URL credentials **before** truncation. It limits depth, fields, string length, and total serialized bytes. Each sanitization also caps aggregate preprocessing at 512 visited values/keys and 131,072 input string characters; exceeding either marks input incomplete. Known environment secrets are refreshed for each sanitization, including credentials set after startup. See [PRIVACY.md](PRIVACY.md) for exact data fields, retention limits, and endpoint overrides. Sanitization is best-effort secret minimization, **not** a DLP guarantee; private facts may remain. Disable the plugin for data that must not leave the machine.

Decision states carry `input_metadata`: `input_complete`, `truncated`, `truncated_fields`, a redaction flag, and original/processed string lengths where available. Depth, field-count, list, string, and byte-budget loss all mark input incomplete. Paths use fixed schema names or numeric positions, not arbitrary user keys. Metadata is included in the byte budget, survives repeated sanitization, and reaches the SDK. No shaping or verification intervention is allowed on incomplete input.

SDK wire logs are suppressed only in this plugin's request context, even with SDK DEBUG logging enabled. Telemetry never contains conversations, tool output, arguments, secret values, or exception messages. Logs expose only bounded decision metadata, fallback categories, latency, model ID, and token usage. Shadow telemetry distinguishes predicted actions (`would_shape`, `would_approve`, `would_nudge`) from actions applied to Hermes, and records mode and completeness flags.

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
HERMES_SOURCE=/path/to/hermes /path/to/hermes/venv/bin/python -m pytest tests/test_hermes*_contract.py -q -W error
```

The dedicated CI job checks out Hermes at `77ecc72bcdd5da0163cca21c8af0e95b26ba3426`, installs its dependencies, and runs every `test_hermes*.py` contract with a fake DecisionEngine. `scripts/run_hermes_integration.py` rejects a missing checkout, a different SHA, an empty report, or any skipped/failed contract. It removes live-test opt-ins and the TypeSafe key from the test environment. Local unit runs can still skip Hermes contracts when no checkout is supplied; the dedicated job cannot.

Run the deterministic evaluation matrix without credentials:

```bash
python scripts/evaluate.py --output /tmp/jev-eval.json
```

It compares disabled, shadow, risk-only, and enforce profiles. Cases include short follow-ups, cached coding work, actionable prompt tails, long tool arguments, fresh chat, risky/read-only actions, native blocks before and after Jev, and valid/inconsistent/truncated completion claims. Reports include false tool removals, unnecessary/missed approval requests, incorrect/missed verification nudges, lost native blocks, behavior differences, engine-call counts, and measured local overhead. Expectations are profile-specific: disabled/shadow are supposed to emit no directives. Timings use a fake engine, not the TypeSafe service. This suite checks plugin guards; it does not establish Jev accuracy or production latency.

Before claiming stable readiness, collect opt-in shadow observations on representative Hermes workflows, review false actions, test real approval delivery on the intended host, and confirm acceptable service latency. Passing synthetic tests is not that evidence.

On Hermes versions exposing the catalog validator, also check the directory plugin before submitting a catalog pin:

```bash
hermes plugins validate /path/to/hermes-plugin-jev
```

The manifest declares all registered hooks and middleware through `provides_hooks` and `provides_middleware`, with `provides_tools: []`. Ordinary CI checks these declarations against registration; the Hermes contract suite checks the real validator when the selected checkout provides it. Use an isolated upstream checkout for compatibility checks rather than updating a running gateway.

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

The demo automatically skips without a key. It classifies four public examples, evaluates a hypothetical build-directory deletion, and assesses a clearly labelled synthetic failed-test scenario. It prints decisions and measured latency. **It never executes the hypothetical commands.** Actual API calls may incur charges. This is a smoke test, not a routing-quality or cost-effectiveness benchmark. Keep live output private; check the [provider terms](THIRD_PARTY.md) before publishing service performance information.

## Limits and next steps

- No provider/model switching, persistent decision database, dashboard, fine-tuning, or agent replacement.
- Initial shaping covers only simple chat and recognized function schemas. High thresholds will often preserve every tool.
- Verification recognizes a small set of direct foreground test/lint/build commands. It cannot prove test relevance or coverage, inspect actual diffs, or follow remote/background jobs to completion.
- Approval emission depends on safe hook ordering; changing hooks concurrently is outside the supported runtime contract. Hermes still owns its hook timeout/re-entrancy guards, including fail-closed behavior if even the cache-only policy callback is delayed by the host.
- The approval context adapter uses Hermes's current internal predicates because the tested host has no public equivalent. Contract tests cover CLI, Telegram, cron, single-query, API-server, and webhook contexts. Unsupported versions abstain.
- Interrupted turns may remain ambiguous for session-only verification until cache expiry; no decision is guessed across turns. SDK clients currently reconnect per request.
- A TTL-bounded cache guarantees reuse while an entry is retained, not forever across process restarts or expiration.
- `DecisionEngine` is a small protocol. An adapter benchmark can implement it without changing hooks; `system-one-adapter-python` is not a runtime dependency.

Next steps include better evidence collection for silent failures, offline adapter contract tests, and delegation recommendations. Hosted-service benchmarks require a review of the applicable [provider terms](THIRD_PARTY.md). Same-provider model routing remains out of V0.
