"""Small, structured file operations executed inside the configured OS sandbox."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path


MAX_FILE_BYTES = 2 * 1024 * 1024
SKIP_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _path(value: str) -> Path:
    target = Path(value).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    return target.resolve(strict=False)


def _read_text(target: Path) -> str:
    if not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("目标不是可读普通文件，或文件超过 2 MiB")
    with target.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def _version(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def run(payload: dict) -> str:
    action = payload.get("action")
    if action in {"read", "write", "edit", "delete"}:
        target = _path(payload["path"])
        if action == "read":
            content = _read_text(target)
            lines = content.splitlines()
            start = max(1, int(payload.get("start_line", 1)))
            end = min(len(lines), int(payload.get("end_line", start + 199)))
            rendered = "\n".join(f"{index}: {line}" for index, line in enumerate(lines[start - 1:end], start))
            if payload.get("include_version"):
                return json.dumps({"text": rendered, "version": _version(content)}, ensure_ascii=False)
            return rendered
        if action == "write":
            if target.exists():
                raise ValueError("文件已存在；请使用 edit_file 修改现有文件")
            content = payload["content"]
            if len(content.encode("utf-8")) > MAX_FILE_BYTES:
                raise ValueError("单次写入不能超过 2 MiB")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8", newline="") as stream:
                stream.write(content)
            return f"已创建 {target}（{len(content)} 个字符）"
        if action == "edit":
            if not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("目标不是可编辑普通文件，或文件超过 2 MiB")
            expected_version = payload.get("expected_version")
            if not isinstance(expected_version, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_version):
                raise ValueError("修改前请先用 read_file 读取文件")
            with target.open("r+", encoding="utf-8", newline="") as stream:
                content = stream.read()
                if _version(content) != expected_version:
                    raise ValueError("文件自上次读取后已更改，请重新读取后再修改")
                old_text = payload["old_text"]
                matches = content.count(old_text)
                if not old_text or matches == 0:
                    raise ValueError("未找到要替换的原文")
                if matches != 1 and not payload.get("replace_all"):
                    raise ValueError(f"原文匹配到 {matches} 处；请缩小匹配范围或明确设置 replace_all")
                replacement = payload["new_text"]
                updated = content.replace(old_text, replacement, -1 if payload.get("replace_all") else 1)
                if len(updated.encode("utf-8")) > MAX_FILE_BYTES:
                    raise ValueError("修改后文件不能超过 2 MiB")
                stream.seek(0)
                stream.write(updated)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
            if payload.get("include_version"):
                return json.dumps({"text": f"已更新 {target}", "version": _version(updated)}, ensure_ascii=False)
            return f"已更新 {target}"
        if not target.is_file():
            raise ValueError("只允许删除普通文件")
        expected_version = payload.get("expected_version")
        if not isinstance(expected_version, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_version):
            raise ValueError("删除前请先用 read_file 读取文件")
        content = _read_text(target)
        if _version(content) != expected_version:
            raise ValueError("文件自上次读取后已更改，请重新读取后再删除")
        target.unlink()
        return f"已删除 {target}"

    if action in {"list", "search"}:
        root = _path(payload.get("directory", "."))
        if not root.is_dir():
            raise ValueError("目录不存在或不是目录")
        pattern = payload.get("pattern", "**/*")
        limit = max(1, min(200, int(payload.get("max_results", 50))))
        query = payload.get("query", "")
        use_regex = bool(payload.get("regex"))
        matcher = re.compile(query, re.IGNORECASE) if use_regex and query else None
        results = []
        for candidate in root.rglob("*"):
            relative = candidate.relative_to(root)
            if candidate.is_symlink() or any(part in SKIP_DIRECTORIES for part in relative.parts):
                continue
            relative_text = relative.as_posix()
            if not fnmatch.fnmatch(relative_text, pattern) and not (
                pattern.startswith("**/") and fnmatch.fnmatch(relative_text, pattern[3:])
            ):
                continue
            if action == "list":
                results.append(f"{'dir ' if candidate.is_dir() else 'file'} {relative.as_posix()}")
            elif candidate.is_file() and candidate.stat().st_size <= MAX_FILE_BYTES:
                try:
                    with candidate.open("r", encoding="utf-8") as stream:
                        for line_number, line in enumerate(stream, 1):
                            found = matcher.search(line) if matcher else query.casefold() in line.casefold()
                            if found:
                                text = line.rstrip()[:400]
                                results.append(f"{relative.as_posix()}:{line_number}: {text}")
                                if len(results) >= limit:
                                    break
                except (UnicodeError, OSError):
                    continue
            if len(results) >= limit:
                break
        return "\n".join(results) if results else "没有找到匹配内容。"

    raise ValueError("未知文件操作")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        print(run(payload))
        return 0
    except Exception as exc:
        print(f"文件操作失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
