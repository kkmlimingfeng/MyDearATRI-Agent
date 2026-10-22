"""Linux Landlock rules for the sandbox's custom filesystem policy."""

from __future__ import annotations

import ctypes
import os
import shlex
import shutil
import stat
import sys
from pathlib import Path
from typing import Any


LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
LANDLOCK_ACCESS_FS_REFER = 1 << 13
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

_MAKE_ACCESS = (
    LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_MAKE_SYM
)
_ALL_HANDLED_ACCESS = (
    LANDLOCK_ACCESS_FS_EXECUTE
    | LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | _MAKE_ACCESS
    | LANDLOCK_ACCESS_FS_REFER
    | LANDLOCK_ACCESS_FS_TRUNCATE
)
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def landlock_abi() -> int:
    if not sys.platform.startswith("linux"):
        return 0
    libc = _libc()
    result = libc.syscall(_SYS_LANDLOCK_CREATE_RULESET, None, 0, LANDLOCK_CREATE_RULESET_VERSION)
    return int(result) if result >= 0 else 0


def _operation_access(permissions: dict[str, bool]) -> int:
    access = 0
    if permissions.get("read"):
        access |= LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR
    if permissions.get("write"):
        access |= _MAKE_ACCESS
    if permissions.get("edit"):
        access |= LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_TRUNCATE
    if permissions.get("delete"):
        access |= LANDLOCK_ACCESS_FS_REMOVE_DIR | LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_REFER
    return access


def _add_path_rule(
    libc: ctypes.CDLL,
    ruleset_fd: int,
    path: str | Path,
    access: int,
    *,
    required: bool = False,
) -> None:
    if not access:
        return
    path = Path(path)
    try:
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode):
            if required:
                raise RuntimeError(f"沙箱权限路径不是目录：{path}")
            return
        path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    except (OSError, AttributeError) as exc:
        if required:
            raise RuntimeError(f"无法应用沙箱权限路径：{path}") from exc
        return
    try:
        rule = _PathBeneathAttr(allowed_access=access, parent_fd=path_fd)
        result = libc.syscall(_SYS_LANDLOCK_ADD_RULE, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(rule), 0)
        if result < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(path))
    finally:
        os.close(path_fd)


def _runtime_paths(command: str = "") -> list[Path]:
    path_directories = {
        Path(part) for part in os.environ.get("PATH", "").split(os.pathsep) if part
    }
    paths = {
        Path("/bin"), Path("/sbin"), Path("/usr/bin"), Path("/usr/sbin"),
        Path("/usr/local/bin"), Path("/usr/local/sbin"), Path("/lib"),
        Path("/lib64"), Path("/usr/lib"), Path("/usr/lib64"),
        Path("/usr/local/lib"), Path("/dev"), Path("/etc/ld.so.cache"),
        Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).resolve().parent,
    }
    paths.update(path_directories)
    executable_names = {"node", "npm", "npx", "uv", "uvx"}
    try:
        for token in shlex.split(command):
            if token.startswith("-") or token in {"&&", "||", ";", "|"}:
                continue
            if "/" not in token and "\\" not in token:
                executable_names.add(token)
            elif Path(token).is_file():
                paths.add(Path(token).resolve().parent)
    except ValueError:
        pass
    for name in executable_names:
        executable = shutil.which(name)
        if not executable:
            continue
        try:
            target = Path(executable).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if target.is_file():
            paths.add(target.parent)
    return sorted(paths, key=lambda path: str(path))


def apply_filesystem_policy(settings: dict[str, Any], command: str = "") -> None:
    """Restrict the current process and children to the selected filesystem policy."""
    abi = landlock_abi()
    if abi < 3:
        raise RuntimeError("当前 Linux 内核不支持安全文件权限隔离（需要 Landlock ABI 3）")

    permissions = settings["permissions"]
    outside_access = _operation_access(permissions["outside"])
    workspace_access = _operation_access(permissions["workspace"])
    handled_access = _ALL_HANDLED_ACCESS
    attr = _RulesetAttr(handled_access_fs=handled_access)
    libc = _libc()
    ruleset_fd = libc.syscall(_SYS_LANDLOCK_CREATE_RULESET, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if ruleset_fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), "landlock_create_ruleset")

    try:
        _add_path_rule(libc, ruleset_fd, "/", outside_access, required=True)
        _add_path_rule(libc, ruleset_fd, settings["workspace"], workspace_access, required=True)

        runtime_access = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR
        for path in _runtime_paths(command):
            _add_path_rule(libc, ruleset_fd, path, runtime_access)

        if libc.prctl(38, 1, 0, 0, 0) < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), "PR_SET_NO_NEW_PRIVS")
        if libc.syscall(_SYS_LANDLOCK_RESTRICT_SELF, ruleset_fd, 0) < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), "landlock_restrict_self")
    finally:
        os.close(ruleset_fd)
