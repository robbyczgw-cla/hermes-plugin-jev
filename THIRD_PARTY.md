# Licensing and third-party software

## Plugin code

This repository is licensed under the [MIT License](LICENSE). Keep its copyright and permission notice when redistributing the software or substantial portions of it. The license does not grant rights to third-party trademarks, hosted services, model weights, or training data.

This is an independent integration. It is not an official TypeSafe AI or Nous Research product and does not claim their endorsement. Thanks to the [Hermes Agent contributors](https://github.com/NousResearch/hermes-agent) for the plugin interfaces and [TypeSafe AI](https://github.com/typesafe-ai/typesafe-sdk-python) for the Python SDK.

## Runtime dependencies

The direct dependency is `typesafe-sdk>=0.6.0,<0.7`, licensed under MIT. Hermes Agent is the host, not a bundled copy. The System One adapter repository was a reference, not an imported or vendored dependency. No SDK, model weights, or Hermes source is bundled in this project's wheel.

The reviewed Python 3.12 dependency installation contained:

- `typesafe-sdk` 0.6.0: MIT.
- `typing_extensions` 4.16.0: PSF-2.0.
- `tenacity` 9.1.4: Apache-2.0.
- `msgspec` 0.21.1: BSD-3-Clause.
- `httpx2` 2.13.0: BSD-3-Clause.
- `truststore` 0.10.4: MIT.
- `idna` 3.20: BSD-3-Clause.
- `httpcore2` 2.13.0: BSD-3-Clause.
- `h11` 0.16.0: MIT.
- `anyio` 4.15.1: MIT.

This list records an inspected installation, not a dependency lock or a claim about every future resolution. Licenses were checked in the installed distribution metadata; each listed distribution includes its own license file. The SDK's shipped MIT notice contains upstream `[year] [fullname]` placeholders. This project does not invent or replace that notice.

These dependency licenses do not require changing this plugin's MIT license. If you redistribute dependencies in a container, binary, or bundle, preserve their actual license/copyright notices and any applicable Apache NOTICE material. Development tools and platform-specific or optional dependencies require their own review when redistributed.

## Hosted Jev service

An MIT-licensed client does not make the hosted API or Jev model open-source. Users supply their own credentials and are responsible for API charges and the terms applying to their account.

Review TypeSafe's [customer agreement](https://typesafe.ai/legal/mca), [privacy policy](https://typesafe.ai/privacy-policy), and [data processing addendum](https://typesafe.ai/legal/data-processing). The published customer agreement's section 2.3 includes restrictions on publishing benchmarks or performance information, model distillation, and certain competing uses. Do not publish live service performance results without checking the agreement that applies to you and obtaining any required permission. Offline tests against synthetic engines are distinct from measurements of the hosted service.

This document describes the inspected software notices and points to provider terms. It is not a legal opinion about an individual deployment or account agreement.
