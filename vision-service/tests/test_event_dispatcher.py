"""Unit tests for vision service EventDispatcher."""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import requests

# Ensure vision-service root is in sys.path
SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from events.event_dispatcher import EventDispatcher, EventDispatchError


class TestEventDispatcher(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock(spec=requests.Session)
        self.dispatcher = EventDispatcher(
            backend_url="http://127.0.0.1:8000",
            timeout=2.0,
            session=self.mock_session,
        )

        self.valid_event = {
            "event_id": "evt_test_001",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 12,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": "2026-10-20T10:05:00Z",
            "evidence": {
                "peak_similarity": 0.612,
                "mean_similarity": 0.589,
                "supporting_frames": 5,
                "total_frames": 6,
                "consistency_pct": 83.33,
                "margin_over_runner_up": 0.35,
                "runner_up_identity": "person_02",
            },
        }

    # ==========================================================================
    # Contract & Preservation Tests
    # ==========================================================================

    def test_format_payload_preserves_all_contract_fields(self):
        """Preserves camera_id, track_id, identity, direction, timestamp, and CV evidence."""
        payload = self.dispatcher.format_payload(self.valid_event)

        self.assertEqual(payload["event_id"], "evt_test_001")
        self.assertEqual(payload["camera_id"], "CAM_ROOM_101_DOOR")
        self.assertEqual(payload["track_id"], 12)
        self.assertEqual(payload["identity"], "person_01")
        self.assertEqual(payload["direction"], "ENTRY")
        self.assertEqual(payload["timestamp"], "2026-10-20T10:05:00Z")
        self.assertEqual(payload["evidence"]["peak_similarity"], 0.612)
        self.assertEqual(payload["evidence"]["mean_similarity"], 0.589)
        self.assertEqual(payload["evidence"]["supporting_frames"], 5)
        self.assertEqual(payload["evidence"]["total_frames"], 6)
        self.assertEqual(payload["evidence"]["consistency_pct"], 83.33)
        self.assertEqual(payload["evidence"]["margin_over_runner_up"], 0.35)
        self.assertEqual(payload["evidence"]["runner_up_identity"], "person_02")

    def test_format_payload_converts_datetime_to_iso(self):
        """Datetime objects are cleanly converted to ISO 8601 strings."""
        event = dict(self.valid_event)
        event["timestamp"] = datetime(2026, 10, 20, 10, 5, 0, tzinfo=timezone.utc)

        payload = self.dispatcher.format_payload(event)
        self.assertIn("2026-10-20T10:05:00", payload["timestamp"])

    def test_format_payload_strips_forbidden_extra_fields(self):
        """Forbidden extra fields (e.g. classroom_id, session_id) are not forwarded."""
        event = dict(self.valid_event)
        event["classroom_id"] = "ROOM_101"
        event["session_id"] = "session_abc"
        event["extra_field"] = "bad"

        payload = self.dispatcher.format_payload(event)
        self.assertNotIn("classroom_id", payload)
        self.assertNotIn("session_id", payload)
        self.assertNotIn("extra_field", payload)

    def test_format_payload_auto_generates_event_id_if_omitted(self):
        """Missing event_id is automatically generated."""
        event = dict(self.valid_event)
        del event["event_id"]

        payload = self.dispatcher.format_payload(event)
        self.assertTrue(payload["event_id"].startswith("evt_"))

    def test_format_payload_raises_on_missing_required_fields(self):
        """Missing mandatory sensory fields raises ValueError."""
        event = dict(self.valid_event)
        del event["identity"]

        with self.assertRaises(ValueError):
            self.dispatcher.format_payload(event)

    # ==========================================================================
    # Successful Dispatch & Ingestion Tests
    # ==========================================================================

    def test_send_event_successful_201_created(self):
        """Backend returning 201 Created is processed successfully."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "event_id": "evt_test_001",
            "status": "accepted",
            "message": "Event successfully ingested",
            "processed_at": "2026-10-20T10:05:01Z",
        }
        self.mock_session.post.return_value = mock_resp

        result = self.dispatcher.send_event(self.valid_event)

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["event_id"], "evt_test_001")
        self.mock_session.post.assert_called_once()
        args, kwargs = self.mock_session.post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8000/api/v1/events")
        self.assertEqual(kwargs["json"]["camera_id"], "CAM_ROOM_101_DOOR")

    def test_send_event_backend_200_duplicate(self):
        """Backend returning 200 OK duplicate is handled cleanly."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "event_id": "evt_test_001",
            "status": "duplicate",
            "message": "Event already processed",
        }
        self.mock_session.post.return_value = mock_resp

        result = self.dispatcher.send_event(self.valid_event)
        self.assertEqual(result["status"], "duplicate")

    # ==========================================================================
    # Duplicate Suppression Tests
    # ==========================================================================

    def test_client_side_deduplication_by_event_id(self):
        """Second call with identical event_id is suppressed locally."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"event_id": "evt_test_001", "status": "accepted"}
        self.mock_session.post.return_value = mock_resp

        # First send
        res1 = self.dispatcher.send_event(self.valid_event)
        self.assertEqual(res1["status"], "accepted")
        self.assertEqual(self.mock_session.post.call_count, 1)

        # Second send with same event_id
        res2 = self.dispatcher.send_event(self.valid_event)
        self.assertEqual(res2["status"], "duplicate")
        self.assertIn("locally", res2["message"])
        # Network request was NOT sent again
        self.assertEqual(self.mock_session.post.call_count, 1)

    def test_client_side_deduplication_by_track(self):
        """Second call with same track_id and direction on same camera is suppressed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"event_id": "evt_test_001", "status": "accepted"}
        self.mock_session.post.return_value = mock_resp

        # First send
        self.dispatcher.send_event(self.valid_event)
        self.assertEqual(self.mock_session.post.call_count, 1)

        # Second send with DIFFERENT event_id but identical track and direction
        event2 = dict(self.valid_event)
        event2["event_id"] = "evt_test_002"
        res2 = self.dispatcher.send_event(event2)

        self.assertEqual(res2["status"], "duplicate")
        self.assertIn("already dispatched", res2["message"])
        self.assertEqual(self.mock_session.post.call_count, 1)

    def test_reset_clears_deduplication_cache(self):
        """Calling reset() clears local cache allowing re-transmission."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"event_id": "evt_test_001", "status": "accepted"}
        self.mock_session.post.return_value = mock_resp

        self.dispatcher.send_event(self.valid_event)
        self.assertEqual(self.mock_session.post.call_count, 1)

        self.dispatcher.reset()

        self.dispatcher.send_event(self.valid_event)
        self.assertEqual(self.mock_session.post.call_count, 2)

    # ==========================================================================
    # HTTP and Network Failure Handling Tests
    # ==========================================================================

    def test_connection_error_raises_clean_event_dispatch_error(self):
        """Connection failure raises descriptive EventDispatchError when raise_on_failure=True."""
        self.mock_session.post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with self.assertRaises(EventDispatchError) as ctx:
            self.dispatcher.send_event(self.valid_event)

        self.assertIn("Connection failed to backend", str(ctx.exception))

    def test_connection_error_returns_dict_when_raise_on_failure_false(self):
        """Connection failure returns error dict when raise_on_failure=False."""
        self.mock_session.post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        result = self.dispatcher.send_event(self.valid_event, raise_on_failure=False)
        self.assertEqual(result["status"], "error")
        self.assertIn("Connection failed", result["message"])

    def test_timeout_error_raises_clean_event_dispatch_error(self):
        """Timeout raises descriptive EventDispatchError."""
        self.mock_session.post.side_effect = requests.exceptions.Timeout("timed out")

        with self.assertRaises(EventDispatchError) as ctx:
            self.dispatcher.send_event(self.valid_event)

        self.assertIn("timed out after 2.0s", str(ctx.exception))

    def test_backend_http_422_rejection_handled_cleanly(self):
        """HTTP 422 Unprocessable Entity raises EventDispatchError with details."""
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = '{"detail": "Unprocessable Entity"}'
        self.mock_session.post.return_value = mock_resp

        with self.assertRaises(EventDispatchError) as ctx:
            self.dispatcher.send_event(self.valid_event)

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Backend rejected event with HTTP 422", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
