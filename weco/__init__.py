import os
import importlib.metadata

# DO NOT EDIT
__pkg_version__ = importlib.metadata.version("weco")
__api_version__ = "v1"

__base_url__ = os.environ.get("WECO_BASE_URL", f"https://api.weco.ai/{__api_version__}")
__dashboard_url__ = os.environ.get("WECO_DASHBOARD_URL", "https://dashboard.weco.ai")

# This deployment's fork identity (the CLI is installed from this fork, not
# PyPI; see the repository's branching policy).
__fork_slug__ = "connollydavid/weco-cli"


def build_identity() -> str:
    """The ``--version`` line: package version, fork, and installed commitish.

    The commitish comes from the install's ``direct_url`` metadata (present
    for git installs, so a checkout names its exact commit); a PyPI or sdist
    install reports an unknown commit rather than guessing.
    """
    import json

    commit = None
    try:
        raw = importlib.metadata.distribution("weco").read_text("direct_url.json")
        if raw:
            direct = json.loads(raw) or {}
            # VCS installs nest the commit under vcs_info; archive installs
            # carry a flat commit_id.
            commit = direct.get("commit_id") or (direct.get("vcs_info") or {}).get("commit_id")
    except Exception:
        commit = None
    if commit:
        return f"weco {__pkg_version__} ({__fork_slug__}@{commit[:12]})"
    return f"weco {__pkg_version__} ({__fork_slug__}, commit unknown)"
