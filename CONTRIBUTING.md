# Contributing

Keep changes scoped to the plugin. Add an offline regression test before fixing a bug. Run pytest, Ruff, and package checks from the README. Changes to Hermes-facing hooks also require the isolated Hermes contract suite against the intended Hermes revision.

Do not weaken Hermes authorization, introduce unbounded state or retries, log prompt/tool bodies, or put real credentials in fixtures. Document any new data sent to TypeSafe. Provider routing and execution orchestration are outside V0.
