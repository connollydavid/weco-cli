"""Generic agent-harness configuration support.

Each harness module reads or writes that harness's own configuration
idiomatically (discovery order, file formats, credential storage) so the
rest of the CLI can consume provider endpoints and credentials without
hardcoding harness assumptions. The modules are pure: they parse and
write what is on disk and never touch the network.
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
from weco.harnesses.zcode import (
    API_KEY_ENV,
    REGIONS,
    ZcodeConfigError,
    merge_config,
    required_exports,
    server_entries,
    write_config,
)

__all__ = [
    "HarnessConfigError",
    "ProviderEndpoint",
    "load_auth",
    "load_opencode_config",
    "resolve_provider_endpoint",
    "strip_jsonc",
    "substitute",
    "API_KEY_ENV",
    "REGIONS",
    "ZcodeConfigError",
    "merge_config",
    "required_exports",
    "server_entries",
    "write_config",
]
