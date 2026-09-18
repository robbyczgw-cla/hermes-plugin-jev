# Changelog

## Unreleased

- Declare hooks and middleware for current Hermes catalog validation; check declarations against plugin registration.
- Document automatic SDK installation on newer Hermes versions and the manual path on older versions.
- Use the current approval-context test imports with a fallback for older Hermes, and test catalog validation when available.

- Refresh environment-secret redaction after startup and replace overlapping known secrets longest-first.
- Document transmitted data, local/provider retention boundaries, dependency licenses, and hosted-service terms.

- Move semantic risk requests into `tool_request` middleware. The policy hook consumes bounded, single-use proposals without network I/O or cache-lock waits.
- Abstain from semantic approval in cron, single-query, API/webhook, and noninteractive contexts. Keep Hermes's deterministic policy checks unchanged.
- Scope approval rule keys to risk dimensions and sanitized action summaries instead of allowlisting every escalation on a tool together.
- Treat observer-collected verification results as historical unless freshness can be established. Reject background, collection-only, and dry-run commands as successful verification.
- Add concurrency, approval-context, evidence, privacy, cache-boundary, and real-loader regression tests.
