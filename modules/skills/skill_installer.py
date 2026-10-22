"""Safe installation of Agent Skills directory archives."""

from __future__ import annotations

import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .base_skill import _parse_frontmatter


MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_UNPACKED_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 1000
MAX_SKILLS_PER_ARCHIVE = 50
SKILL_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")


def _safe_member_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("技能压缩包包含不安全的文件路径")
    if path.parts and re.match(r"^[A-Za-z]:", path.parts[0]):
        raise ValueError("技能压缩包包含不安全的文件路径")
    return path


def _extract_archive(archive: zipfile.ZipFile, destination: Path) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise ValueError("技能压缩包文件数量过多")
    if sum(info.file_size for info in entries) > MAX_UNPACKED_BYTES:
        raise ValueError("技能压缩包解压后超过 64 MB")

    actual_total = 0
    for info in entries:
        relative = _safe_member_path(info.filename)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError("技能压缩包不能包含符号链接")
        target = destination.joinpath(*relative.parts)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        actual_file = 0
        with archive.open(info) as source, target.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                actual_file += len(chunk)
                actual_total += len(chunk)
                if actual_file > MAX_UNPACKED_BYTES or actual_total > MAX_UNPACKED_BYTES:
                    raise ValueError("技能压缩包解压后超过 64 MB")
                output.write(chunk)


def install_skill_archive(content: bytes, destination: Path) -> list[dict[str, Any]]:
    """Install one or more SKILL.md directories without replacing existing skills."""
    if not isinstance(content, bytes) or not content or len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError("技能压缩包为空或超过 16 MB")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(__import__("io").BytesIO(content))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("技能文件必须是有效的 ZIP 压缩包") from exc

    with archive, tempfile.TemporaryDirectory(prefix="skill-import-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        _extract_archive(archive, staging)
        roots = sorted({path.parent for path in staging.rglob("SKILL.md")})
        if not roots:
            raise ValueError("压缩包中没有包含 SKILL.md 的技能目录")
        if len(roots) > MAX_SKILLS_PER_ARCHIVE:
            raise ValueError("单个压缩包最多导入 50 个技能")
        if any(parent in child.parents for parent in roots for child in roots if parent != child):
            raise ValueError("技能目录不能互相嵌套")

        plans = []
        for root in roots:
            skill_file = root / "SKILL.md"
            content_text = skill_file.read_text(encoding="utf-8")
            frontmatter, _ = _parse_frontmatter(content_text)
            name = frontmatter.get("name") or root.name
            if not isinstance(name, str) or not SKILL_NAME.fullmatch(name):
                raise ValueError(f"技能名称无效: {name!r}（需使用小写字母、数字、下划线或连字符）")
            if not frontmatter.get("description"):
                raise ValueError(f"技能 {name} 缺少 frontmatter description")
            target = destination / name
            if target.exists():
                raise ValueError(f"技能已存在: {name}")
            plans.append((name, root, target, frontmatter))

        installed = []
        moved = []
        try:
            for name, root, target, frontmatter in plans:
                shutil.move(str(root), str(target))
                moved.append(target)
                installed.append({
                    "id": name,
                    "name": frontmatter.get("name", name),
                    "description": frontmatter["description"],
                    "installed": True,
                })
        except Exception:
            for path in moved:
                shutil.rmtree(path, ignore_errors=True)
            raise
        return installed
