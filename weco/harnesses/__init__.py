"""Generic agent-harness configuration support.

Each harness module reads that harness's own configuration idiomatically
(discovery order, file formats, credential storage) so the rest of the CLI
can consume provider endpoints and credentials without hardcoding harness
assumptions. The readers are pure: they parse what is on disk and never
touch the network.
"""

from weco.harnesses.opencode import (
    HarnessConfigError,
    ProviderEndpoint,
    load_auth,
    load_opencode_config,
    resolve_provider_endpoint,
    strip_jsonc,
    substitute,
)

__all__ = [
    "HarnessConfigError",
    "ProviderEndpoint",
    "load_auth",
    "load_opencode_config",
    "resolve_provider_endpoint",
    "strip_jsonc",
    "substitute",
]
