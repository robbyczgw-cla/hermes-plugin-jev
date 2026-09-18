# Contributing

Keep changes scoped to the plugin. Add an offline regression test before fixing a bug. Run pytest, Ruff, and package checks from the README. Changes to Hermes-facing hooks also require the isolated Hermes contract suite against the intended Hermes revision.

Do not weaken Hermes authorization, introduce unbounded state or retries, log prompt/tool bodies, or put real credentials in fixtures. Document any new data sent to TypeSafe. Provider routing and execution orchestration are outside V0.

Contributions are accepted under this repository's MIT license. Preserve authorship and third-party notices; describe copied or adapted code and its origin. See [THIRD_PARTY.md](THIRD_PARTY.md) before adding dependencies or publishing live service benchmarks. Use synthetic prompts and credentials in tests.

Before publishing changes, scan all Git refs and the source/build contents with a secret scanner. A clean scan is not a guarantee: also inspect commit metadata, Actions logs, package contents, and non-code GitHub surfaces. Never suppress a real secret finding merely to make CI pass.
