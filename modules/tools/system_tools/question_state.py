"""Process-local state shared by the question tool and HTTP API."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any


_lock = threading.Lock()
_active: dict[str, Any] | None = None


def current_question() -> dict[str, Any] | None:
    with _lock:
        if _active is None:
            return None
        return {key: _active[key] for key in ("id", "questions", "created_at")}


def answer_question(question_id: str, answers: list[dict]) -> bool:
    if not isinstance(answers, list) or not 1 <= len(answers) <= 8:
        raise ValueError("answers 必须包含每个问题的回答")
    with _lock:
        active = _active
        if active is None or active["id"] != question_id or active["event"].is_set():
            return False
        questions = {question["id"]: question for question in active["questions"]}
        normalized = []
        seen_ids = set()
        for answer in answers:
            if not isinstance(answer, dict) or set(answer) - {"id", "selected", "custom"}:
                raise ValueError("回答格式无效")
            answer_id = answer.get("id")
            selected = answer.get("selected")
            custom = answer.get("custom", "")
            question = questions.get(answer_id) if isinstance(answer_id, str) else None
            if question is None or answer_id in seen_ids:
                raise ValueError("回答的问题 id 无效或重复")
            if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
                raise ValueError("selected 必须是字符串数组")
            if not isinstance(custom, str) or len(custom) > 2000:
                raise ValueError("custom 不能超过 2000 个字符")
            options = question["options"]
            if any(item not in options for item in selected) or len(set(selected)) != len(selected):
                raise ValueError("回答包含未提供的选项")
            if not question["multi_select"] and len(selected) > 1:
                raise ValueError("单选问题不能选择多个选项")
            if custom.strip() and not question["multi_select"]:
                selected = []
            item = {"id": answer_id, "selected": selected}
            if custom.strip():
                item["custom"] = custom.strip()
            normalized.append(item)
            seen_ids.add(answer_id)
        if seen_ids != set(questions):
            raise ValueError("必须为每个问题提交一项回答；跳过的问题 selected 传空数组")
        active["answer"] = normalized
        active["event"].set()
        return True


def cancel_pending_question(reason: str = "本次运行已停止") -> None:
    with _lock:
        active = _active
        if active is not None and not active["event"].is_set():
            active["answer"] = reason
            active["cancelled"] = True
            active["event"].set()


def wait_for_answer(questions: list[dict], timeout_seconds: int) -> str | dict:
    global _active
    pending = {
        "id": uuid.uuid4().hex,
        "questions": questions,
        "created_at": time.time(),
        "event": threading.Event(),
        "answer": None,
        "cancelled": False,
    }
    with _lock:
        if _active is not None:
            raise RuntimeError("已有一个问题正在等待回答")
        _active = pending
    try:
        completed = pending["event"].wait(timeout_seconds)
        with _lock:
            if not completed and not pending["event"].is_set():
                if _active is pending:
                    _active = None
                return "用户暂未回答此问题，等待已超时。"
            if pending["cancelled"]:
                return "本次运行已停止，请结束当前任务。"
        return {"answers": pending["answer"]}
    finally:
        with _lock:
            if _active is pending:
                _active = None
