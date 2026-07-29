import unittest
from unittest.mock import MagicMock, patch

import requests

from nistiprint_shared.services.shopee_chat_api import (
    get_all_chat_messages,
    get_chat_messages,
)
from nistiprint_shared.services.shopee_chat_service import (
    classify_shopee_webhook,
    extract_chat_provider_event_id,
    normalize_chat_message,
    shopee_chat_ingest_service,
)


MESSAGE_CONTENT = {
    "message_id": "2302748948493123953",
    "shop_id": 165103149,
    "request_id": "request-1",
    "from_id": 165105353,
    "from_user_name": "buyer",
    "to_id": 947151379,
    "to_user_name": "seller",
    "message_type": "text",
    "content": {"text": "Oi"},
    "conversation_id": "709122092476686867",
    "created_timestamp": 1726044721,
    "region": "BR",
    "business_type": 0,
    "is_in_chatbot_session": False,
    "quoted_msg": {"message_id": ""},
    "sub_account_id": 0,
    "sub_account_name": "0",
}


def message_push(**overrides):
    content = {**MESSAGE_CONTENT, **overrides}
    return {
        "msg_id": "",
        "data": {"type": "message", "region": "BR", "content": content},
        "shop_id": 165103149,
        "code": 10,
        "timestamp": 1726044722,
    }


class ShopeeChatServiceTest(unittest.TestCase):
    def test_classifies_chat_and_order_codes(self):
        self.assertEqual(classify_shopee_webhook({"code": 10}), "chat")
        self.assertEqual(classify_shopee_webhook({"code": 3}), "order")

    def test_uses_nested_message_id_for_push_deduplication(self):
        self.assertEqual(
            extract_chat_provider_event_id(message_push()),
            MESSAGE_CONTENT["message_id"],
        )

    def test_normalizes_documented_message_types(self):
        contents = {
            "text": {"text": "Oi"},
            "video": {"video_url": "https://example/video.mp4"},
            "image": {"image_url": "https://example/image.jpg"},
            "item": {"item_id": 123, "shop_id": 456},
            "faq_liveagent": {"text": "FAQ"},
        }
        for message_type, content in contents.items():
            with self.subTest(message_type=message_type):
                row = normalize_chat_message(
                    {**MESSAGE_CONTENT, "message_type": message_type, "content": content},
                    integration_id=7,
                )
                self.assertEqual(row["type"], message_type)
                self.assertEqual(row["content"], content)
                self.assertEqual(row["provider_message_id"], MESSAGE_CONTENT["message_id"])
                self.assertEqual(row["business_type"], 0)

    def test_notification_is_skipped_without_lookup_or_write(self):
        payload = {
            "code": 10,
            "data": {
                "type": "notification",
                "content": {
                    "conversation_id": "4670954831706433",
                    "type": "mark_as_replied",
                },
            },
        }
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver, patch(
            "nistiprint_shared.services.shopee_chat_service.supabase_db"
        ) as db:
            result = shopee_chat_ingest_service.process(payload)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["event_status"], "skipped_chat_notification")
        resolver.resolve_marketplace_by_shop_id.assert_not_called()
        db.table.assert_not_called()

    def test_affiliate_chat_is_skipped(self):
        result = shopee_chat_ingest_service.process(message_push(business_type=11))
        self.assertEqual(result["event_status"], "skipped_affiliate_chat")

    def test_documented_message_envelope_is_upserted(self):
        db = MagicMock()
        db.table.return_value.upsert.return_value.execute.return_value.data = []
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver, patch(
            "nistiprint_shared.services.shopee_chat_service.supabase_db", db
        ):
            resolver.resolve_marketplace_by_shop_id.return_value = {
                "id": 7,
                "plataforma_slug": "shopee",
            }
            result = shopee_chat_ingest_service.process(message_push(), webhook_event_id=88)
        self.assertEqual(result["status"], "success")
        rows = db.table.return_value.upsert.call_args.args[0]
        self.assertEqual(rows[0]["provider_message_id"], MESSAGE_CONTENT["message_id"])
        self.assertEqual(rows[0]["webhook_event_id"], 88)
        self.assertEqual(
            db.table.return_value.upsert.call_args.kwargs["on_conflict"],
            "installed_integration_id,provider_message_id",
        )

    def test_malformed_message_is_retryable_error(self):
        payload = message_push(message_id=None)
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver:
            resolver.resolve_marketplace_by_shop_id.return_value = {
                "id": 7,
                "plataforma_slug": "shopee",
            }
            result = shopee_chat_ingest_service.process(payload)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "invalid_chat_message")

    def test_reconciliation_upserts_complete_api_history(self):
        db = MagicMock()
        db.table.return_value.upsert.return_value.execute.return_value.data = []
        with patch(
            "nistiprint_shared.services.shopee_chat_service.get_all_chat_messages",
            return_value={"messages": [MESSAGE_CONTENT], "complete": True},
        ), patch("nistiprint_shared.services.shopee_chat_service.supabase_db", db):
            result = shopee_chat_ingest_service.reconcile_conversation(
                {"id": 7, "config": {"shop_id": 165103149}},
                MESSAGE_CONTENT["conversation_id"],
            )
        self.assertEqual(result["status"], "success")
        rows = db.table.return_value.upsert.call_args.args[0]
        self.assertEqual(rows[0]["ingestion_source"], "sellerchat_api")


class ShopeeChatApiTest(unittest.TestCase):
    def setUp(self):
        self.integration = {
            "config": {"partner_id": 1, "partner_key": "secret", "shop_id": 2},
            "access_token": "token",
        }

    @patch("nistiprint_shared.services.shopee_chat_api.requests.get")
    def test_uses_string_offset_and_reads_nested_next_offset(self, request_get):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "error": "",
            "response": {
                "messages": [MESSAGE_CONTENT],
                "page_result": {
                    "next_offset": "922337203685477580812345",
                    "page_size": 1,
                },
            },
        }
        request_get.return_value = response
        result = get_chat_messages(
            self.integration,
            "conversation-1",
            offset="922337203685477580799999",
            message_id_list=["2302748948493123953"],
        )
        params = request_get.call_args.kwargs["params"]
        self.assertEqual(params["offset"], "922337203685477580799999")
        self.assertEqual(params["business_type"], 0)
        self.assertEqual(result["next_offset"], "922337203685477580812345")

    @patch("nistiprint_shared.services.shopee_chat_api.get_chat_messages")
    def test_fetches_all_pages(self, get_page):
        get_page.side_effect = [
            {"messages": [{"message_id": "2"}], "next_offset": "2"},
            {"messages": [{"message_id": "1"}], "next_offset": None},
        ]
        result = get_all_chat_messages(self.integration, "conversation-1")
        self.assertTrue(result["complete"])
        self.assertEqual([row["message_id"] for row in result["messages"]], ["2", "1"])
        self.assertEqual(get_page.call_args_list[1].kwargs["offset"], "2")

    @patch("nistiprint_shared.services.shopee_chat_api.requests.get")
    def test_classifies_rate_limit_and_auth_errors(self, request_get):
        rate_limited = MagicMock(status_code=429, text="rate limited")
        unauthorized = MagicMock(status_code=401, text="unauthorized")
        request_get.side_effect = [rate_limited, unauthorized]
        rate_result = get_chat_messages(self.integration, "conversation-1")
        auth_result = get_chat_messages(self.integration, "conversation-1")
        self.assertEqual(rate_result["error_type"], "rate_limit")
        self.assertTrue(rate_result["retryable"])
        self.assertEqual(auth_result["error_type"], "authentication_error")
        self.assertFalse(auth_result["retryable"])

    @patch(
        "nistiprint_shared.services.shopee_chat_api.requests.get",
        side_effect=requests.Timeout("timeout"),
    )
    def test_classifies_timeout_as_retryable(self, _request_get):
        result = get_chat_messages(self.integration, "conversation-1")
        self.assertEqual(result["error_type"], "timeout")
        self.assertTrue(result["retryable"])


if __name__ == "__main__":
    unittest.main()
