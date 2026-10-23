"""Blocking batch user-question tool bridged to the chat run-status API."""

from __future__ import annotations

import json
import re
from typing import TypedDict

from modules.tools.base_tool import system_tool
from modules.tools.system_tools.question_state import wait_for_answer


class AskUserQuestion(TypedDict):
    id: str
    question: str
    options: list[str]
    multi_select: bool


@system_tool(timeout=1810, retries=0, parallel=False)
def ask_user_question(questions: list[AskUserQuestion], timeout_seconds: int = 300) -> str:
    """Ask one or more user questions in a single blocking interaction.

    Args:
        questions: One to eight questions with unique ids, text, choices, and multi-select behavior
        timeout_seconds: How long to wait, from 10 to 1800 seconds

    Returns:
        A JSON object containing one answer entry per question, or an explicit timeout/cancellation result.
    """
    if not isinstance(questions, list) or not 1 <= len(questions) <= 8:
        return "提问失败：questions 必须包含 1 到 8 个问题。"
    normalized = []
    seen_ids = set()
    for item in questions:
        if not isinstance(item, dict) or set(item) - {"id", "question", "options", "multi_select"}:
            return "提问失败：每个问题都必须符合问题结构。"
        question_id = item.get("id")
        text = item.get("question")
        options = item.get("options")
        multi_select = item.get("multi_select")
        if not isinstance(question_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", question_id) or question_id in seen_ids:
            return "提问失败：问题 id 必须唯一且只包含字母、数字、下划线或连字符。"
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            return "提问失败：每个问题都需要 1 到 2000 个字符。"
        if not isinstance(options, list) or len(options) > 8 or any(
            not isinstance(option, str) or not option.strip() or len(option) > 200 for option in options
        ):
            return "提问失败：每个问题最多可以有 8 个非空选项。"
        if not isinstance(multi_select, bool):
            return "提问失败：multi_select 必须是布尔值。"
        seen_ids.add(question_id)
        normalized.append({
            "id": question_id,
            "question": text.strip(),
            "options": [option.strip() for option in options],
            "multi_select": multi_select,
        })
    if isinstance(timeout_seconds, bool):
        return "提问失败：等待时长无效。"
    try:
        timeout = max(10, min(1800, int(timeout_seconds)))
    except (TypeError, ValueError, OverflowError):
        return "提问失败：等待时长无效。"
    try:
        result = wait_for_answer(normalized, timeout)
    except RuntimeError as exc:
        return f"提问失败：{exc}。"
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)
