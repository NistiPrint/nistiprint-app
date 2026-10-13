import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from nistiprint_shared.services.ai_personalization_service import get_chat_messages


class Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, _columns):
        return self

    def eq(self, field, value):
        self.rows = [row for row in self.rows if str(row.get(field)) == str(value)]
        return self

    def gte(self, field, value):
        self.rows = [row for row in self.rows if str(row.get(field)) >= str(value)]
        return self

    def order(self, field, desc=False):
        self.rows.sort(key=lambda row: str(row.get(field)), reverse=desc)
        return self

    def range(self, start, end):
        self.rows = self.rows[start:end + 1]
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class Database:
    def __init__(self, conversations, messages):
        self.conversations = conversations
        self.messages = messages

    def table(self, name):
        return Query(list(self.conversations if name == "conversas_chat_shopee" else self.messages))


class ShopeeChatTimelineTest(unittest.TestCase):
    def test_joins_buyer_sessions_deduplicates_and_isolates_integration(self):
        when = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conversations = [
            {"conversation_id": 10, "buyer_user_id": 42, "installed_integration_id": 7},
            {"conversation_id": 20, "buyer_user_id": 42, "installed_integration_id": 7},
            {"conversation_id": 30, "buyer_user_id": 42, "installed_integration_id": 8},
        ]
        def message(ident, cid, integration, buyer=42, username="buyer"):
            return {"id": ident, "conversation_id": cid,
                    "installed_integration_id": integration, "from_id": buyer,
                    "to_id": 99, "from_user_name": username,
                    "to_user_name": "seller", "created_at": when,
                    "type": "text", "display_content": ident}
        messages = [message("a", 10, 7), message("b", 20, 7),
                    message("other-shop", 30, 8),
                    message("other-buyer", 40, 7, buyer=50),
                    {**message("old", 10, 7),
                     "created_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()},
                    {**message("legacy", 20, 7), "from_id": None, "to_id": None}]
        db = Database(conversations, messages)
        with patch("nistiprint_shared.services.ai_personalization_service.supabase_db", db):
            result = get_chat_messages("buyer", integration_id=7, buyer_id=42)
            by_id_only = get_chat_messages("", integration_id=7, buyer_id=42)
        self.assertEqual({row["id"] for row in result}, {"a", "b", "legacy"})
        self.assertEqual(len(result), 3)
        self.assertEqual({row["id"] for row in by_id_only}, {"a", "b", "legacy"})

    def test_buyer_id_requires_integration(self):
        with self.assertRaises(ValueError):
            get_chat_messages("buyer", buyer_id=42)


if __name__ == "__main__":
    unittest.main()
