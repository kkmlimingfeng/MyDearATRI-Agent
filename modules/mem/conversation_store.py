"""Local persistence for ordinary chat transcripts and their summaries."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_STORE_LOCK = threading.RLock()


class ConversationStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.transcript_dir = self.root / "conversations"
        self.index_path = self.root / "index.json"

    def _read_index(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}
        conversations = raw.get("conversations", {}) if isinstance(raw, dict) else {}
        if not isinstance(conversations, dict):
            return {}
        return {
            key: value for key, value in conversations.items()
            if isinstance(key, str) and _CONVERSATION_ID.fullmatch(key) and isinstance(value, dict)
        }

    def _write_index(self, conversations: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"version": 1, "conversations": conversations}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.index_path)

    @staticmethod
    def _timestamp(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        timestamp = int(value)
        return timestamp if timestamp > 0 else None

    @staticmethod
    def _complete_prefix(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        last_answer = max(
            (index for index, message in enumerate(messages) if message["role"] == "assistant"),
            default=-1,
        )
        return messages[: last_answer + 1]

    def save(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("会话记录格式无效")
        if payload.get("test_run") is True or payload.get("source") == "workflow-test":
            return {"saved": False, "skipped": True}

        conversation_id = payload.get("id")
        if not isinstance(conversation_id, str) or not _CONVERSATION_ID.fullmatch(conversation_id):
            raise ValueError("会话 ID 无效")
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list) or len(raw_messages) > 20000:
            raise ValueError("会话消息必须是最多 20000 条的数组")

        messages: list[dict[str, Any]] = []
        for item in raw_messages:
            if not isinstance(item, dict) or not isinstance(item.get("role"), str) or item["role"] not in {"user", "assistant"}:
                continue
            content = item.get("content")
            if not isinstance(content, str) or not content.strip() or item.get("error"):
                continue
            if len(content) > 200000:
                raise ValueError("单条会话消息不能超过 200 KB")
            message = {"role": item["role"], "content": content}
            sent_at = self._timestamp(item.get("sentAt", item.get("sent_at")))
            if sent_at is not None:
                message["sent_at"] = sent_at
            messages.append(message)

        if not messages:
            return {"saved": False, "empty": True}

        title = payload.get("title", "新的对话")
        if not isinstance(title, str):
            title = "新的对话"
        title = title.strip()[:120] or "新的对话"
        updated_at = self._timestamp(payload.get("updatedAt", payload.get("updated_at")))
        if updated_at is None:
            updated_at = int(datetime.now(timezone.utc).timestamp() * 1000)
        created_at = self._timestamp(payload.get("createdAt", payload.get("created_at")))
        if created_at is None:
            created_at = next((message.get("sent_at") for message in messages if message.get("sent_at")), updated_at)

        completed = self._complete_prefix(messages)
        dates = sorted({
            datetime.fromtimestamp(message["sent_at"] / 1000, timezone.utc).astimezone().date().isoformat()
            for message in messages if message.get("sent_at")
        })
        transcript_path = self.transcript_dir / f"{conversation_id}.jsonl"
        records = [{
            "type": "conversation",
            "id": conversation_id,
            "title": title,
            "created_at": created_at,
            "updated_at": updated_at,
        }]
        records.extend({"type": "message", **message} for message in messages)
        transcript = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)

        with _STORE_LOCK:
            index = self._read_index()
            previous = index.get(conversation_id, {})
            if updated_at < int(previous.get("updated_at", 0) or 0):
                return {"saved": False, "stale": True, "conversation": previous}
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            temporary = transcript_path.with_suffix(".jsonl.tmp")
            temporary.write_text(transcript, encoding="utf-8")
            os.replace(temporary, transcript_path)
            summary_message_count = min(
                len(completed), max(0, int(previous.get("summary_message_count", 0) or 0))
            )
            summary_turn_count = min(
                len([item for item in completed if item["role"] == "assistant"]),
                max(0, int(previous.get("summary_turn_count", 0) or 0)),
            )
            entry = {
                **previous,
                "id": conversation_id,
                "title": title,
                "created_at": min(created_at, int(previous.get("created_at", created_at) or created_at)),
                "updated_at": updated_at,
                "path": f"conversations/{conversation_id}.jsonl",
                "message_count": len(messages),
                "complete_message_count": len(completed),
                "turn_count": sum(item["role"] == "assistant" for item in completed),
                "dates": dates,
                "summary_message_count": summary_message_count,
                "summary_turn_count": summary_turn_count,
                "summary_status": "ready" if previous.get("summary") and summary_message_count >= len(completed) else "pending",
            }
            index[conversation_id] = entry
            self._write_index(index)
        return {"saved": True, "conversation": entry}

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        if not isinstance(conversation_id, str) or not _CONVERSATION_ID.fullmatch(conversation_id):
            raise ValueError("会话 ID 无效")
        with _STORE_LOCK:
            entry = self._read_index().get(conversation_id)
            if entry is None:
                return None
            path = self.transcript_dir / f"{conversation_id}.jsonl"
            try:
                records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            except (OSError, json.JSONDecodeError):
                raise ValueError("会话原文无法读取")
        messages = [
            {key: record[key] for key in ("role", "content", "sent_at") if key in record}
            for record in records[1:]
            if isinstance(record, dict) and record.get("type") == "message"
        ]
        return {"conversation": entry, "messages": messages}

    def list(self) -> list[dict[str, Any]]:
        with _STORE_LOCK:
            entries = list(self._read_index().values())
        entries.sort(key=lambda entry: int(entry.get("updated_at", 0) or 0), reverse=True)
        return entries

    def delete(self, conversation_id: str) -> bool:
        if not isinstance(conversation_id, str) or not _CONVERSATION_ID.fullmatch(conversation_id):
            raise ValueError("会话 ID 无效")
        with _STORE_LOCK:
            index = self._read_index()
            if conversation_id not in index:
                return False
            index.pop(conversation_id, None)
            self._write_index(index)
            try:
                (self.transcript_dir / f"{conversation_id}.jsonl").unlink()
            except FileNotFoundError:
                pass
        return True

    def update_summary(
        self,
        conversation_id: str,
        summary: str,
        summarized_message_count: int,
        summarized_turn_count: int,
    ) -> dict[str, Any]:
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("摘要内容不能为空")
        with _STORE_LOCK:
            index = self._read_index()
            entry = index.get(conversation_id)
            if entry is None:
                raise ValueError("会话记录不存在")
            if not 0 <= summarized_message_count <= int(entry.get("complete_message_count", entry.get("message_count", 0))):
                raise ValueError("摘要覆盖的消息数量无效")
            if not 0 <= summarized_turn_count <= int(entry.get("turn_count", 0)):
                raise ValueError("摘要覆盖的轮数无效")
            entry = {
                **entry,
                "summary": summary.strip()[:12000],
                "summary_message_count": summarized_message_count,
                "summary_turn_count": summarized_turn_count,
                "summary_updated_at": int(datetime.now(timezone.utc).timestamp() * 1000),
                "summary_status": "ready" if summarized_message_count >= int(entry.get("complete_message_count", entry.get("message_count", 0))) else "pending",
            }
            index[conversation_id] = entry
            self._write_index(index)
        return entry


conversation_store = ConversationStore(Path(__file__).resolve().parents[2] / "data" / "memory")
