"""Test environment: preserve the cloud-mode expectations of the suite.

Local is the shipped default, but the suite's inherited tests exercise the
cloud paths that upstream wrote them against. Pin the mode to cloud for the
whole run; local-mode tests set WECO_MODE explicitly per test.
"""

import os

os.environ.setdefault("WECO_MODE", "weco")
