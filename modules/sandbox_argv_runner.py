"""Apply sandbox policy before executing a structured argument vector."""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    if len(sys.argv) != 3:
        print("沙箱启动参数无效", file=sys.stderr)
        return 2
    serialized_argv, serialized_settings = sys.argv[1:]
    try:
        command_args = json.loads(serialized_argv)
        settings = json.loads(serialized_settings)
        if (
            not isinstance(command_args, list)
            or not command_args
            or any(not isinstance(arg, str) or "\0" in arg for arg in command_args)
        ):
            raise ValueError("沙箱命令参数无效")

        from modules.sandbox_landlock import apply_filesystem_policy

        if settings.get("_apply_landlock", True) is True and settings.get("permission") in {"custom", "workspace"}:
            apply_filesystem_policy(settings, command=shlex.join(command_args[:2]))
        os.execvpe(command_args[0], command_args, os.environ.copy())
    except Exception as exc:
        print(f"沙箱权限未能生效，命令已拒绝执行：{exc}", file=sys.stderr)
        return 125
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
