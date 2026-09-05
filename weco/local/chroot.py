"""A reproducible minimal chroot, entered the systemd way.

The manifest names a locked rootfs (an archive URL and its SHA-256, or a
local archive plus its hash): the same manifest always builds the same
tree, and the build verifies the hash before unpacking. Entry is
``systemd-run --user`` over the unpacked root (the user manager's
namespaced rootless chroot, call/0004's note) with the workspace bind-
mounted and GPU device nodes bound where the host allows it. User
namespaces cannot create device nodes, so a build that needs device nodes
the host will not pass through documents the rootful fallback
(``sudo systemd-nspawn`` or a plain rootful ``chroot``).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import shutil
import tarfile


class ChrootError(RuntimeError):
    """Raised when a chroot manifest or rootfs cannot be used."""


@dataclasses.dataclass(frozen=True)
class ChrootManifest:
    """A locked, reproducible chroot definition."""

    name: str
    rootfs_url: str
    rootfs_sha256: str
    command: tuple[str, ...]
    # Absolute device paths to bind into the chroot (e.g. /dev/nvidia0)
    device_binds: tuple[str, ...] = ()
    # Host driver libraries/directories copied in beside the rootfs (GPU
    # userspace must match the host kernel driver)
    host_driver_paths: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> "ChrootManifest":
        required = ("name", "rootfs_url", "rootfs_sha256", "command")
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ChrootError(f"chroot manifest is missing {', '.join(missing)}")
        if not isinstance(data["command"], list):
            raise ChrootError("chroot manifest command must be a list")
        return cls(
            name=str(data["name"]),
            rootfs_url=str(data["rootfs_url"]),
            rootfs_sha256=str(data["rootfs_sha256"]),
            command=tuple(str(part) for part in data["command"]),
            device_binds=tuple(str(p) for p in data.get("device_binds", [])),
            host_driver_paths=tuple(str(p) for p in data.get("host_driver_paths", [])),
        )


def verify_sha256(archive: pathlib.Path, expected: str) -> None:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != expected.lower():
        raise ChrootError(f"{archive}: sha256 {digest} does not match the manifest's {expected}")


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for member in tar.getmembers():
        name = member.name
        if name.startswith("/") or ".." in pathlib.PurePosixPath(name).parts:
            raise ChrootError(f"refusing to extract unsafe member {name!r}")
        if member.isdev():
            # Device nodes cannot be created by an unprivileged build anyway;
            # refuse rather than silently skip.
            raise ChrootError(f"refusing device member {name!r}")
        members.append(member)
    return members


def unpack_rootfs(archive: pathlib.Path, dest: pathlib.Path) -> None:
    """Unpack a rootfs archive into dest, refusing unsafe members."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive) as tar:
            members = _safe_members(tar)
            if hasattr(tarfile, "data_filter"):
                tar.extractall(dest, members=members, filter="data")
            else:
                tar.extractall(dest, members=members)
    except tarfile.TarError as exc:
        raise ChrootError(f"{archive}: not a readable archive ({exc})") from exc


def build_rootfs(manifest: ChrootManifest, *, archive: pathlib.Path, root: pathlib.Path) -> pathlib.Path:
    """Verify and unpack the rootfs; record a lock file for reproducibility.

    The same archive and manifest always produce the same tree and the
    same lock record (the archive's name and hash, the manifest's fields).
    """
    verify_sha256(archive, manifest.rootfs_sha256)
    rootfs = root / manifest.name / "rootfs"
    if rootfs.exists():
        shutil.rmtree(rootfs)
    unpack_rootfs(archive, rootfs)
    lock = {
        "name": manifest.name,
        "rootfs_url": manifest.rootfs_url,
        "rootfs_sha256": manifest.rootfs_sha256,
        "archive": archive.name,
    }
    lock_path = root / manifest.name / "manifest.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return rootfs


def systemd_run_argv(
    manifest: ChrootManifest, rootfs: pathlib.Path, *, workspace: pathlib.Path, workspace_target: str = "/work"
) -> list[str]:
    """The systemd-run --user command that enters the chroot.

    The workspace binds read-write (the loop edits code there); declared
    device nodes bind through where the host permits. Device nodes that a
    user namespace cannot pass through need the documented rootful
    fallback; this command is the rootless path.
    """
    argv = [
        "systemd-run",
        "--user",
        "--collect",
        "--wait",
        f"--unit=weco-chroot-{manifest.name}",
        f"--property=RootDirectory={rootfs}",
        f"--property=WorkingDirectory={workspace_target}",
        f"--property=BindPaths={workspace}:{workspace_target}",
    ]
    for device in manifest.device_binds:
        argv.append(f"--property=BindPaths={device}:{device}")
    argv.extend(manifest.command)
    return argv
