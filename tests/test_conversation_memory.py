import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.runtime_manager import RuntimeState
from modules.mem.conversation_store import ConversationStore
import web_server
from web_server import update_conversation_summaries


def make_conversation(conversation_id="chat_test", turns=2, updated_at=1000):
    messages = []
    for turn in range(turns):
        messages.extend([
            {"role": "user", "content": f"问题 {turn + 1}", "sentAt": updated_at + turn * 2},
            {"role": "assistant", "content": f"回答 {turn + 1}", "sentAt": updated_at + turn * 2 + 1},
        ])
    return {
        "id": conversation_id,
        "title": "记忆测试",
        "createdAt": 1000,
        "updatedAt": updated_at + turns * 2,
        "source": "chat",
        "messages": messages,
    }


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self.temporary.name) / "memory")

    def tearDown(self):
        self.temporary.cleanup()

    def test_regular_chat_is_saved_as_jsonl_and_test_runs_are_skipped(self):
        skipped = self.store.save({**make_conversation(), "test_run": True})
        self.assertTrue(skipped["skipped"])
        self.assertEqual(self.store.list(), [])

        result = self.store.save(make_conversation())
        archive = self.store.get("chat_test")

        self.assertTrue(result["saved"])
        self.assertEqual(len(archive["messages"]), 4)
        self.assertEqual(archive["conversation"]["turn_count"], 2)
        self.assertEqual(archive["conversation"]["complete_message_count"], 4)
        self.assertEqual(len((self.store.transcript_dir / "chat_test.jsonl").read_text(encoding="utf-8").splitlines()), 5)

    def test_summary_progress_survives_new_messages_and_stale_snapshots_do_not_overwrite(self):
        self.store.save(make_conversation(turns=2, updated_at=2000))
        self.store.update_summary("chat_test", "前两轮摘要", 4, 2)
        self.store.save(make_conversation(turns=3, updated_at=3000))
        stale = self.store.save(make_conversation(turns=2, updated_at=2000))
        entry = self.store.get("chat_test")["conversation"]

        self.assertTrue(stale["stale"])
        self.assertEqual(entry["summary"], "前两轮摘要")
        self.assertEqual(entry["summary_message_count"], 4)
        self.assertEqual(entry["summary_status"], "pending")


class ConversationSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self.temporary.name) / "memory")

    def tearDown(self):
        self.temporary.cleanup()

    def test_incremental_summary_uses_new_messages_and_manual_update_rebuilds_from_source(self):
        first = make_conversation(turns=2, updated_at=2000)
        self.store.save(first)
        calls = []

        def summarize(_agent, _llm_id, previous_summary, messages):
            calls.append((previous_summary, messages))
            return f"summary-{len(messages)}"

        runtime = RuntimeState(agent=object(), bindings={"llm_id": "test-llm"}, started=True)
        with patch("web_server.conversation_store", self.store), \
                patch.object(web_server._runtime_manager, "state", runtime), \
                patch("web_server._summarize_history", side_effect=summarize):
            initial = update_conversation_summaries({"conversation_ids": ["chat_test"]})
            second = make_conversation(turns=3, updated_at=3000)
            self.store.save(second)
            incremental = update_conversation_summaries({"conversation_ids": ["chat_test"]})
            rebuilt = update_conversation_summaries({"conversation_ids": ["chat_test"], "force": True})

        self.assertEqual(initial["updated"], 1)
        self.assertEqual(incremental["updated"], 1)
        self.assertEqual(rebuilt["updated"], 1)
        self.assertEqual(calls[0][0], "")
        self.assertEqual(len(calls[0][1]), 4)
        self.assertEqual(calls[1][0], "summary-4")
        self.assertEqual(len(calls[1][1]), 2)
        self.assertEqual(calls[2][0], "")
        self.assertEqual(len(calls[2][1]), 6)

    def test_unanswered_message_is_archived_but_not_sent_for_summary(self):
        conversation = make_conversation(turns=0)
        conversation["messages"] = [{"role": "user", "content": "聊到一半就下线"}]
        self.store.save(conversation)

        result = update_conversation_summaries({"conversation_ids": ["chat_test"]})
        entry = self.store.get("chat_test")["conversation"]

        self.assertEqual(result["updated"], 0)
        self.assertEqual(entry["turn_count"], 0)
        self.assertEqual(entry["summary_status"], "pending")


if __name__ == "__main__":
    unittest.main()
