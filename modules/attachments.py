"""Validation and text/image preparation for chat attachments."""

from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree

from PIL import Image, ImageOps


MAX_ATTACHMENT_COUNT = 10
MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 24 * 1024 * 1024
MAX_EXTRACTED_TEXT_CHARS = 80_000
MAX_VIDEO_FRAMES = 8
MAX_TOTAL_VIDEO_FRAMES = 16
MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_EDGE = 2048

TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".log", ".py", ".js", ".jsx",
    ".ts", ".tsx", ".html", ".css", ".xml", ".yaml", ".yml", ".toml",
    ".ini", ".sql", ".sh", ".rs", ".java", ".go", ".c", ".h", ".cpp",
}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm", ".odt", ".ods", ".odp"} | TEXT_EXTENSIONS
IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "BMP"}


def _attachment_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("附件缺少文件名")
    name = PurePosixPath(value.replace("\\", "/")).name.strip()[:180]
    if not name or name in {".", ".."}:
        raise ValueError("附件文件名无效")
    return name


def _decode_base64(value: Any, name: str, limit: int) -> bytes:
    if not isinstance(value, str) or len(value) > (limit * 4 // 3) + 16:
        raise ValueError(f"{name} 超过附件大小限制")
    if value.startswith("data:"):
        _, separator, value = value.partition(",")
        if not separator:
            raise ValueError(f"{name} 的数据格式无效")
    try:
        content = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{name} 的数据格式无效") from exc
    if not content or len(content) > limit:
        raise ValueError(f"{name} 为空或超过附件大小限制")
    return content


def _normalize_image(content: bytes, name: str) -> str:
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.format not in IMAGE_FORMATS:
                raise ValueError(f"{name} 的图片格式不支持")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError(f"{name} 图片尺寸过大")
            source.seek(0)
            image = ImageOps.exif_transpose(source.copy())
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError(f"{name} 不是有效图片") from exc

    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        image.save(output, format="PNG", optimize=True)
        mime_type = "image/png"
    else:
        image.convert("RGB").save(output, format="JPEG", quality=86, optimize=True)
        mime_type = "image/jpeg"
    normalized = output.getvalue()
    if len(normalized) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"{name} 压缩后仍超过附件大小限制")
    return f"data:{mime_type};base64,{base64.b64encode(normalized).decode('ascii')}"


def _read_zip_xml(archive: zipfile.ZipFile, member: str) -> ElementTree.Element:
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise ValueError("文档结构不完整，无法读取") from exc
    if info.file_size > 8 * 1024 * 1024:
        raise ValueError("文档内的文本数据过大")
    with archive.open(info) as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("文档内的文本数据过大")
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise ValueError("文档内容格式无效") from exc


def _extract_docx(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = _read_zip_xml(archive, "word/document.xml")
    paragraphs = []
    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        text = "".join(node.text or "" for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _extract_pptx(content: bytes) -> str:
    slide_names = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
            if match:
                slide_names.append((int(match.group(1)), name))
        slides = [_read_zip_xml(archive, name) for _, name in sorted(slide_names)]
    paragraphs = []
    for slide in slides:
        for paragraph in slide.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}p"):
            text = "".join(node.text or "" for node in paragraph.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t"))
            if text:
                paragraphs.append(text)
    return "\n".join(paragraphs)


def _extract_xlsx(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = _read_zip_xml(archive, "xl/sharedStrings.xml")
            shared_strings = [
                "".join(node.text or "" for node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))
                for item in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si")
            ]
        sheets = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
            key=lambda name: int(re.search(r"sheet(\d+)", name).group(1)),
        )
        rows = []
        for sheet_index, name in enumerate(sheets, start=1):
            root = _read_zip_xml(archive, name)
            rows.append(f"[工作表 {sheet_index}]")
            for row in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
                values = []
                for cell in row.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                    if cell.attrib.get("t") == "inlineStr":
                        text = "".join(node.text or "" for node in cell.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))
                    else:
                        value = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                        if value is None or value.text is None:
                            continue
                        text = value.text
                    if cell.attrib.get("t") == "s":
                        try:
                            text = shared_strings[int(text)]
                        except (ValueError, IndexError):
                            pass
                    values.append(text)
                if values:
                    rows.append("\t".join(values))
                if sum(map(len, rows)) > MAX_EXTRACTED_TEXT_CHARS:
                    return "\n".join(rows)[:MAX_EXTRACTED_TEXT_CHARS]
    return "\n".join(rows)


def _extract_odf(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = _read_zip_xml(archive, "content.xml")
    text_tags = {
        "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p",
        "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}h",
    }
    return "\n".join("".join(node.text or "" for node in item.iter()) for item in root.iter() if item.tag in text_tags)


def _extract_document(name: str, content: bytes) -> str:
    extension = PurePosixPath(name).suffix.lower()
    try:
        if extension in TEXT_EXTENSIONS:
            text = content.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError(f"{name} 不是可读取的文本文件")
            return text
        if extension in {".docx", ".docm"}:
            return _extract_docx(content)
        if extension in {".pptx", ".pptm"}:
            return _extract_pptx(content)
        if extension in {".xlsx", ".xlsm"}:
            return _extract_xlsx(content)
        if extension in {".odt", ".ods", ".odp"}:
            return _extract_odf(content)
        if extension == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise ValueError("读取 PDF 需要安装 pypdf，请更新项目依赖") from exc
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise ValueError(f"{name} 已加密，无法读取")
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
                if sum(map(len, pages)) >= MAX_EXTRACTED_TEXT_CHARS:
                    break
            return "\n".join(pages)
    except (UnicodeDecodeError, zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"{name} 无法解析") from exc
    raise ValueError(f"暂不支持 {PurePosixPath(name).suffix or '此格式'} 文档")


def prepare_chat_attachments(user_input: str, attachments: Any) -> dict[str, Any]:
    """Return text for workflow nodes and normalized image parts for the active LLM."""
    if not isinstance(user_input, str):
        raise ValueError("消息内容必须是文本")
    if attachments is None:
        attachments = []
    if not isinstance(attachments, list) or len(attachments) > MAX_ATTACHMENT_COUNT:
        raise ValueError(f"一次最多上传 {MAX_ATTACHMENT_COUNT} 个附件")

    prompt_parts = [user_input.strip()] if user_input.strip() else []
    image_parts = []
    total_bytes = 0
    frame_count = 0
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError("附件信息格式无效")
        name = _attachment_name(item.get("name"))
        kind = item.get("kind")
        if kind == "image":
            raw = _decode_base64(item.get("data"), name, MAX_ATTACHMENT_BYTES)
            total_bytes += len(raw)
            image_parts.append({"type": "image_url", "image_url": {"url": _normalize_image(raw, name)}})
            prompt_parts.append(f"[图片附件：{name}]")
        elif kind == "video":
            frames = item.get("frames")
            if not isinstance(frames, list) or not frames or len(frames) > MAX_VIDEO_FRAMES:
                raise ValueError(f"{name} 视频需要包含 1 到 {MAX_VIDEO_FRAMES} 个采样画面")
            if frame_count + len(frames) > MAX_TOTAL_VIDEO_FRAMES:
                raise ValueError(f"视频总采样画面不能超过 {MAX_TOTAL_VIDEO_FRAMES} 帧")
            prompt_parts.append(f"[视频附件：{name}，共采样 {len(frames)} 帧]")
            for index, frame in enumerate(frames, start=1):
                if not isinstance(frame, dict):
                    raise ValueError(f"{name} 的第 {index} 帧格式无效")
                raw = _decode_base64(frame.get("data"), f"{name} 第 {index} 帧", MAX_ATTACHMENT_BYTES)
                total_bytes += len(raw)
                if total_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
                    raise ValueError("附件总大小不能超过 24 MB")
                timestamp = frame.get("timestamp")
                if not isinstance(timestamp, (int, float)) or not 0 <= timestamp <= 24 * 60 * 60:
                    raise ValueError(f"{name} 的视频时间戳无效")
                image_parts.append({"type": "text", "text": f"[视频画面 {index}，{timestamp:.1f} 秒]"})
                image_parts.append({"type": "image_url", "image_url": {"url": _normalize_image(raw, name)}})
            frame_count += len(frames)
        elif kind == "document":
            extension = PurePosixPath(name).suffix.lower()
            if extension not in DOCUMENT_EXTENSIONS:
                raise ValueError(f"暂不支持 {name}，请上传 PDF、DOCX、XLSX、PPTX 或常见文本文件")
            raw = _decode_base64(item.get("data"), name, MAX_ATTACHMENT_BYTES)
            total_bytes += len(raw)
            extracted = _extract_document(name, raw).strip()
            if not extracted:
                extracted = "（未提取到可读取的文字内容）"
            prompt_parts.append(f"[文档附件：{name}]\n{extracted[:MAX_EXTRACTED_TEXT_CHARS]}")
        else:
            raise ValueError(f"{name} 的附件类型不支持")
        if total_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
            raise ValueError("附件总大小不能超过 24 MB")

    if not prompt_parts:
        raise ValueError("请输入消息或选择附件")
    prompt = "\n\n".join(prompt_parts)
    if len(prompt) > MAX_EXTRACTED_TEXT_CHARS * 2:
        raise ValueError("消息和附件提取出的文本过长")
    return {"text": prompt, "image_parts": image_parts}
