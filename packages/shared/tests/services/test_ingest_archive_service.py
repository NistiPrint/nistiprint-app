import hashlib
import os
import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.ingest_archive_service import archive_dataset_once


class IngestArchiveServiceTest(unittest.TestCase):
    @patch("nistiprint_shared.services.ingest_archive_service.supabase_db")
    def test_finalizes_only_after_object_verification(self, database):
        rows = [{"id": 7, "received_at": "2026-07-01T10:00:00+00:00", "raw_body": "{}"}]
        fetch = MagicMock(data=rows)
        finalize = MagicMock(data=123)
        database.rpc.side_effect = [MagicMock(execute=MagicMock(return_value=fetch)),
                                    MagicMock(execute=MagicMock(return_value=finalize))]
        s3 = MagicMock()

        def head(**_kwargs):
            body = s3.put_object.call_args.kwargs["Body"]
            return {"ContentLength": len(body),
                    "Metadata": {"sha256": hashlib.sha256(body).hexdigest()}}

        s3.head_object.side_effect = head
        with patch.dict(os.environ, {"INGEST_ARCHIVE_S3_BUCKET": "archive-test"}):
            self.assertEqual(archive_dataset_once("webhook_payloads", client=s3), 1)
        self.assertEqual(database.rpc.call_args_list[-1].args[0], "finalize_ingest_archive_batch")

    @patch("nistiprint_shared.services.ingest_archive_service.supabase_db")
    def test_does_not_finalize_when_checksum_metadata_differs(self, database):
        database.rpc.return_value.execute.return_value.data = [
            {"id": 8, "created_at": "2026-07-01T10:00:00+00:00"}
        ]
        s3 = MagicMock()
        def wrong_checksum(**_kwargs):
            body = s3.put_object.call_args.kwargs["Body"]
            return {"ContentLength": len(body), "Metadata": {"sha256": "wrong"}}

        s3.head_object.side_effect = wrong_checksum
        with patch.dict(os.environ, {"INGEST_ARCHIVE_S3_BUCKET": "archive-test"}):
            with self.assertRaises(RuntimeError):
                archive_dataset_once("pedido_ingest_log", client=s3)
        self.assertEqual(database.rpc.call_count, 1)


if __name__ == "__main__":
    unittest.main()
