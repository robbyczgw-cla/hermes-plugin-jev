# A bounded shadow trial

Use this checklist before considering enforce mode. Shadow observes decisions; it does not remove tools, request approvals, or ask the agent to continue. Enabled stages still send bounded input to TypeSafe and incur API charges. Read [PRIVACY.md](../PRIVACY.md) first.

## Keep the trial separate

Use a disposable Hermes home or a separate test profile. Do not copy your production history, memory, credentials file, or private documents into it. Supply only the TypeSafe credential required for the trial through your normal secret mechanism. Use a separate Python environment for test dependencies.

Install the pinned runtime from the [quickstart](../README.md#quickstart), initially disabled. Run this trial only after the install scanner's findings have been reviewed. `--no-enable` does not bypass scanning. If installation is blocked, stop; do not disable the scanner to complete a test.

Start with [examples/config.shadow.yaml](../examples/config.shadow.yaml). Keep `mode: shadow` and `risk_gate.block_unbindable: false`. To observe completion and tool-shaping signals, set `verify.enabled: true` and `tool_shaping.enabled: true` in the disposable profile only. This does not turn on enforcement while mode remains shadow.

Check `hermes jev status` in that environment before starting. The SDK must be installed in the interpreter running Hermes. A successful package build or a key present in another interpreter does not prove the plugin is active.

## Exercise the boundaries

Use public text and a scratch project, not a real deletion or deployment:

1. **Read-only task:** inspect this repository's README and identify its Python/SDK requirements. Keep the complete tool list available. The read-only tool bypass should not request risk assessment.
2. **Passing verification:** run a small, passing test and report what the test actually returned. Record the real process exit status and output. An observed pass remains historical evidence; it does not prove that later code is tested.
3. **Completion contradiction:** in a test harness, pair real failing-test output with an explicitly counterfactual success claim. Observe whether `would_nudge` is recorded. Never present the counterfactual claim as an actual task result.
4. **Out-of-scope action:** submit a hypothetical deletion to the decision stage when the task only asks for inspection. Do not execute the command. Observe `would_approve`; this means a human confirmation would be requested in enforce mode, never that permission was granted.
5. **Native denial:** use the offline Hermes contract tests to check that a deterministic block still wins. Do not perform a dangerous action to prove a guard works.

The included synthetic demo is a smaller API smoke:

```bash
jev-router demo
```

It never executes the hypothetical tools. Bare scripts have no human-approval surface, so the demo's direct synthetic risk query is not proof that an attended Hermes hook dispatched correctly. For that, use the real plugin loader and an attended CLI or gateway test session. A real host contract test with a fake Jev engine proves a different boundary from a live API test.

## Record observations privately

Record the exact plugin and Hermes commits, effective mode, enabled stages, task labels, actual test exit statuses, SDK call success/fallback, and whether input was complete. Compare the request and tool definitions before and after middleware. Check that no policy directive, argument change, tool removal, or verification continuation occurred in shadow.

Keep `would_approve`, `would_nudge`, and `would_shape` separate from actual behavior. A timeout or abstention is not a correct negative classification. A small set of selected examples cannot establish false-positive rates, accuracy, token savings, or production safety.

Telemetry is process-local. `hermes jev status` in a new shell does not retrieve a running gateway's counters. Preserve the bounded metadata from the process that handled the trial; do not collect full prompts, API keys, private output, or conversation history for convenience.

Keep live service outputs and timing/usage measurements outside the repository. Review the [hosted-service terms](../THIRD_PARTY.md#hosted-jev-service) before sharing service performance information. This document provides a procedure, not a hosted-model benchmark or published test result.

## Exit without changing production

Stop the disposable Hermes process. Confirm that production config and enabled plugins are unchanged. Do not promote to enforce mode automatically, even if every selected example behaved as expected. Review representative workload observations and the remaining abstentions first.
