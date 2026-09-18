# Privacy and data flow

Enabling Jev for Hermes with an API key allows it to send task content to a remote service. This is not a local-only plugin. Secret redaction reduces exposure; it does not make private text safe to upload.

## What leaves the process

The plugin uses the official `typesafe-sdk`. Its default endpoint is `https://api.typesafe.ai`. SDK 0.6.x also reads `TYPESAFE_BASE_URL`; an override changes the destination of both requests and API-key authentication. Only configure an endpoint you trust. Network proxies and other transport settings require the same review.

Each request includes a Jev model ID, fixed decision questions, and a bounded state object:

- **Turn classification:** current user message, platform name, and Hermes agent-model identifier.
- **Tool-risk assessment:** current user message, tool name, selected tool arguments, platform, and classified intent. Shell commands, API payloads, filenames, or code can occur inside those arguments. Read-only bypasses and unattended contexts skip this risk request, not all plugin requests.
- **Coding verification:** current user message, intent, changed file paths, the proposed final response, and bounded verification observations. Observations can include a command, exit-status interpretation, and an excerpt of test output.

The plugin does not send the full conversation history or its cache's session/turn/tool-call IDs as explicit fields. Those identifiers, personal information, or other private content may still appear inside supplied text. It does not independently open repository files, but tool arguments and output can contain their contents. The API key is sent for authentication, not as decision-state data. The remote service also sees ordinary request metadata, including the connecting IP address.

## Redaction and bounds

Before truncation, the sanitizer removes the configured API key, known secret values from secret-named environment variables, credential fields, recognizable token formats, bearer/basic credentials, private keys, and URL credentials. It checks current environment values on each sanitization, including values set after plugin startup. It also retains the initial known-secret set; it does not retain an unlimited history of every rotated credential. Longer known secrets are replaced before shorter overlapping values.

Environment-value matching covers values of at least six characters. Pattern matching is best effort: unknown formats, encoded secrets, natural-language personal details, and credentials embedded in arbitrary content can survive. Do not use this plugin for data that may not leave the machine.

`state_max_bytes` defaults to 8,000 bytes with a 16,000-byte maximum. Additional limits bound nesting, field counts, and strings. These limits reduce data volume, not sensitivity.

## Local state and logs

The plugin keeps bounded in-memory turn state, verification observations, approval proposals, and metadata-only telemetry. Turn-cache entries become eligible for expiration after the configured TTL (1,800 seconds by default); cleanup happens on cache activity or session end, not as a secure deletion timer. Approval proposals expire after ten seconds and are single-use. Process termination releases plugin state; this is not a guarantee of secure memory erasure.

The plugin creates no persistent decision database and has no separate analytics endpoint. Its telemetry contains decision metadata, timing, model IDs, token usage, and fixed error categories, not raw prompt/tool bodies. SDK wire logging is suppressed within plugin requests. Hermes and the host logging configuration determine where emitted metadata is stored and for how long.

Human approval prompts contain a bounded, sanitized action summary. Hermes or a gateway may retain those prompts as part of its own chat, approval, or logging records. Other plugins, host tracing, proxies, and provider-side logs are outside this plugin's control.

## Provider policy is separate

TypeSafe's [privacy policy](https://typesafe.ai/privacy-policy) states that input is not used to train or fine-tune models. It also describes U.S. hosting, service-provider access, and retention for as long as reasonably necessary; this is **not a zero-retention promise**. Its [customer agreement](https://typesafe.ai/legal/mca) and [data processing addendum](https://typesafe.ai/legal/data-processing) describe additional contractual terms.

These are provider statements, not guarantees made or independently verified by this project. Review the current documents and your account's agreement before sending personal, regulated, or confidential data. This plugin does not establish GDPR compliance, a data-processing agreement, or a right to upload someone else's data.

## Disable remote decisions

```bash
hermes plugins disable jev-router
```

Start a new Hermes process after changing plugin settings. For gateways, use a controlled restart outside an active turn. Disabling only classification, risk assessment, or verification leaves the other enabled features able to send requests. A request already in flight can run until its transport timeout; disabling a plugin does not retract data already sent.

Ordinary tests use synthetic fixtures and a fake HTTP transport. Live demos require explicit credentials and can incur charges. Do not publish private prompts, credentials, raw live output, or service performance measurements in issues or CI logs.
