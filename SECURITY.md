# Security

Jev is an advisory remote classifier, not an authorization boundary. Hermes owns policy enforcement, approval, and execution. Read [PRIVACY.md](PRIVACY.md) for transmitted data and redaction limits, and the README for timeout and hook-ordering behavior.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/robbyczgw-cla/hermes-plugin-jev/security/advisories/new) when GitHub offers it for this repository. Availability depends on repository settings and visibility; this document does not imply that the channel is enabled.

If private reporting is unavailable, do not publish vulnerability details. You may open an issue asking the maintainer to enable private reporting, without exploit details, credentials, private conversations, internal addresses, or raw service output. Use synthetic reproductions once a private channel is established.

If a credential was exposed, revoke or rotate it at the provider. Removing a file or rewriting Git history does not invalidate a credential or remove every cached copy.

## Scope and maintenance

Reports about secret redaction, unintended data transmission, approval handling, or plugin packaging are relevant here. Report vulnerabilities in Hermes Agent or the TypeSafe SDK to their respective maintainers when they are not caused by this integration. Do not probe the hosted TypeSafe service without authorization.

The current development branch is the maintained code line; there is no separate long-term-support branch or guaranteed response-time commitment. Probabilistic decisions, unknown secret formats, host logs, and provider-side retention are not security guarantees supplied by this plugin.
