"""Local configuration and directory browsing for the command sandbox."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

from modules.sandbox_landlock import landlock_abi


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SANDBOX_CONFIG_PATH = PROJECT_ROOT / "config" / "sandbox.json"
DEFAULT_SETTINGS = {"workspace": str(PROJECT_ROOT), "permission": "workspace"}
SANDBOX_ACTIONS = ("read", "write", "edit", "delete")
WORKSPACE_PERMISSIONS = {
    "workspace": {"read": True, "write": True, "edit": True, "delete": True},
    "outside": {"read": True, "write": False, "edit": False, "delete": False},
}
FULL_PERMISSIONS = {
    "workspace": {action: True for action in SANDBOX_ACTIONS},
    "outside": {action: True for action in SANDBOX_ACTIONS},
}
_config_lock = threading.Lock()
_WINDOWS_DRIVE_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def _path_from_user_input(value: str) -> Path:
    expanded = os.path.expandvars(value.strip())
    windows_path = _WINDOWS_DRIVE_PATH.match(expanded)
    if windows_path and sys.platform.startswith("linux"):
        drive, remainder = windows_path.groups()
        path = Path("/mnt") / drive.lower() / remainder.replace("\\", "/")
    else:
        path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _resolve_user_path(value: str) -> Path:
    try:
        return _path_from_user_input(value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("目录不存在或无法访问") from exc


def _validate_permission_matrix(value: Any) -> dict[str, dict[str, bool]]:
    if not isinstance(value, dict):
        raise ValueError("自定义权限矩阵格式无效")
    result: dict[str, dict[str, bool]] = {}
    for scope in ("workspace", "outside"):
        scope_value = value.get(scope)
        if not isinstance(scope_value, dict):
            raise ValueError("权限矩阵缺少工作空间内或外的权限")
        result[scope] = {}
        for action in SANDBOX_ACTIONS:
            allowed = scope_value.get(action)
            if not isinstance(allowed, bool):
                raise ValueError("权限矩阵中的权限必须是勾选状态")
            result[scope][action] = allowed
    return result


def _validate_settings(settings: Any) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise ValueError("沙箱设置格式无效")
    workspace = settings.get("workspace", DEFAULT_SETTINGS["workspace"])
    permission = settings.get("permission", DEFAULT_SETTINGS["permission"])
    if not isinstance(workspace, str) or not workspace.strip() or len(workspace) > 4096:
        raise ValueError("请选择有效的工作空间路径")
    if not isinstance(permission, str) or permission not in {"workspace", "full", "custom"}:
        raise ValueError("沙箱权限模式无效")

    try:
        path = _resolve_user_path(workspace)
    except ValueError as exc:
        raise ValueError("工作空间不存在或无法访问") from exc
    if not path.is_dir():
        raise ValueError("工作空间必须是一个目录")
    if permission != "full" and path == Path(path.anchor):
        raise ValueError("工作空间权限模式不能选择文件系统根目录")
    if permission == "workspace":
        permissions = {scope: dict(actions) for scope, actions in WORKSPACE_PERMISSIONS.items()}
    elif permission == "full":
        permissions = {scope: dict(actions) for scope, actions in FULL_PERMISSIONS.items()}
    else:
        permissions = _validate_permission_matrix(settings.get("permissions"))
        for action in SANDBOX_ACTIONS:
            if permissions["outside"][action] and not permissions["workspace"][action]:
                raise ValueError("工作空间外的权限不能高于工作空间内")
    return {"workspace": str(path), "permission": permission, "permissions": permissions}


def load_sandbox_settings() -> dict[str, Any]:
    if not SANDBOX_CONFIG_PATH.is_file():
        return _validate_settings(DEFAULT_SETTINGS)
    try:
        payload = json.loads(SANDBOX_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("沙箱设置文件无法读取") from exc
    return _validate_settings(payload)


def save_sandbox_settings(settings: Any) -> dict[str, Any]:
    validated = _validate_settings(settings)
    SANDBOX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = SANDBOX_CONFIG_PATH.with_suffix(".json.tmp")
    with _config_lock:
        temporary_path.write_text(json.dumps(validated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(SANDBOX_CONFIG_PATH)
    return validated


def browse_sandbox_directories(path: Any = None) -> dict[str, Any]:
    if path is None or path == "":
        current = Path(load_sandbox_settings()["workspace"])
    elif not isinstance(path, str) or len(path) > 4096:
        raise ValueError("目录路径无效")
    else:
        current = _resolve_user_path(path)
    if not current.is_dir():
        raise ValueError("路径不是目录")

    directories = []
    try:
        with os.scandir(current) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        directories.append({"name": entry.name, "path": str(Path(entry.path))})
                except OSError:
                    continue
    except OSError as exc:
        raise ValueError("无法读取该目录") from exc
    directories.sort(key=lambda item: item["name"].casefold())
    parent = current.parent if current.parent != current else None
    return {
        "path": str(current),
        "parent": str(parent) if parent else None,
        "directories": directories,
    }


def sandbox_runtime_info() -> dict[str, Any]:
    abi = landlock_abi()
    firejail_available = shutil.which("firejail") is not None
    return {
        "platform": sys.platform,
        "python": sys.executable,
        "firejail_available": firejail_available,
        "landlock_abi": abi,
        "filesystem_permissions_available": firejail_available and abi >= 3,
        "custom_permissions_available": firejail_available and abi >= 3,
    }
