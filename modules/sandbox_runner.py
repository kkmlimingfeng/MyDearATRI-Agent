"""Apply sandbox policy in a child process before starting the requested shell."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    if len(sys.argv) != 3:
        print("沙箱启动参数无效", file=sys.stderr)
        return 2
    command, serialized_settings = sys.argv[1:]
    try:
        settings = json.loads(serialized_settings)
        from modules.sandbox_landlock import apply_filesystem_policy

        if settings.get("permission") in {"custom", "workspace"}:
            apply_filesystem_policy(settings, command=command)
        os.execvpe("bash", ["bash", "-c", command], os.environ.copy())
    except Exception as exc:
        print(f"沙箱文件权限未能生效，命令已拒绝执行：{exc}", file=sys.stderr)
        return 125
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
