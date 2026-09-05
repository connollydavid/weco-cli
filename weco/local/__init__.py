"""Local-mode execution support: container and chroot drivers.

Local mode runs evaluation work on the user's own infrastructure,
systemd-idiomatically: containers as generated Quadlet units driven by
systemctl, and a reproducible chroot entered through systemd-run --user
over hash-verified contents (call/0004's note records the pattern, with
the rootful fallback where direct GPU device access demands it).
"""

from weco.local.quadlet import ContainerSpec, install_unit, render_container_unit, run_unit, unit_name
from weco.local.chroot import ChrootError, ChrootManifest, build_rootfs, systemd_run_argv

__all__ = [
    "ContainerSpec",
    "install_unit",
    "render_container_unit",
    "run_unit",
    "unit_name",
    "ChrootError",
    "ChrootManifest",
    "build_rootfs",
    "systemd_run_argv",
]
