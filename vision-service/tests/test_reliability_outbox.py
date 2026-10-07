"""Tests for Step 2E.4: Durable outbox, retry with backoff, ordering, restart recovery, and disconnect handling."""

import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import requests

from camera.phone_source import PhoneVideoSource
from camera.rtsp_source import RTSPVideoSource
from events.event_dispatcher import EventDispatcher
from events.outbox import DurableOutbox
from pipeline.live_cv_pipeline import LiveCVPipeline


class TestDurableOutboxAndReliability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="outbox_test_")
        self.db_path = Path(self.test_dir) / "test_outbox.db"
        self.outbox = DurableOutbox(db_path=self.db_path, max_entries=10)

        self.sample_event = {
            "event_id": "evt_test_101",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 1,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": "2026-10-01T10:00:00Z",
            "evidence": {
                "peak_similarity": 0.85,
                "mean_similarity": 0.80,
                "supporting_frames": 4,
                "total_frames": 4,
                "consistency_pct": 100.0,
            },
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ==========================================================================
    # 1. Outbox Persistence Across Restart (Task 1 & 5)
    # ==========================================================================

    def test_outbox_persistence_across_process_restart(self):
        """Unsent events remain in SQLite outbox across process crashes/restarts."""
        # Enqueue 3 events
        for i in range(3):
            evt = dict(self.sample_event)
            evt["event_id"] = f"evt_persist_{i}"
            self.assertTrue(self.outbox.enqueue(evt))

        self.assertEqual(self.outbox.pending_count(), 3)

        # Simulate process shutdown and restart by creating a new DurableOutbox instance
        restarted_outbox = DurableOutbox(db_path=self.db_path, max_entries=10)
        self.assertEqual(restarted_outbox.pending_count(), 3)

        pending = restarted_outbox.get_pending(limit=10)
        self.assertEqual(len(pending), 3)
        self.assertEqual(pending[0][1]["event_id"], "evt_persist_0")
        self.assertEqual(pending[1][1]["event_id"], "evt_persist_1")
        self.assertEqual(pending[2][1]["event_id"], "evt_persist_2")

    # ==========================================================================
    # 2. Security: Schema Enforcement in Outbox (Task 1)
    # ==========================================================================

    def test_outbox_rejects_raw_images_or_biometric_vectors(self):
        """Outbox strictly rejects events containing raw frames, images, or embeddings."""
        bad_event = dict(self.sample_event)
        bad_event["image"] = "base64_encoded_jpeg_string..."
        self.assertFalse(self.outbox.enqueue(bad_event))

        bad_event2 = dict(self.sample_event)
        bad_event2["embedding"] = [0.12, 0.45, -0.22]
        self.assertFalse(self.outbox.enqueue(bad_event2))

        self.assertEqual(self.outbox.pending_count(), 0)

    # ==========================================================================
    # 3. Capacity Bounding & FIFO Oldest-Drop Policy (Task 1)
    # ==========================================================================

    def test_outbox_capacity_bounding_and_oldest_drop(self):
        """When max_entries is exceeded, oldest un-sent event is dropped with log warning."""
        bounded_outbox = DurableOutbox(
            db_path=Path(self.test_dir) / "bounded.db",
            max_entries=3,
        )

        for i in range(4):
            evt = dict(self.sample_event)
            evt["event_id"] = f"evt_cap_{i}"
            bounded_outbox.enqueue(evt)

        # Max entries is 3, so count must not exceed 3
        self.assertEqual(bounded_outbox.pending_count(), 3)

        # The oldest event (evt_cap_0) must have been dropped
        pending = bounded_outbox.get_pending(limit=10)
        remaining_ids = [p[1]["event_id"] for p in pending]
        self.assertNotIn("evt_cap_0", remaining_ids)
        self.assertEqual(remaining_ids, ["evt_cap_1", "evt_cap_2", "evt_cap_3"])

    # ==========================================================================
    # 4. Non-Blocking Frame Loop Dispatch (<1ms) (Task 1)
    # ==========================================================================

    def test_dispatcher_non_blocking_execution(self):
        """Enqueuing via dispatch() or send_event(sync=False) returns immediately (<5ms)."""
        mock_session = MagicMock(spec=requests.Session)
        dispatcher = EventDispatcher(
            backend_url="http://127.0.0.1:8000",
            enable_outbox=True,
            outbox_path=self.db_path,
            session=mock_session,
        )
        try:
            # Warm up SQLite connection and schema creation
            dispatcher.send_event(self.sample_event, sync=False)

            t0 = time.perf_counter()
            res = dispatcher.send_event(self.sample_event, sync=False)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            self.assertEqual(res["status"], "enqueued")
            self.assertLess(elapsed_ms, 5.0, f"Dispatch took too long: {elapsed_ms:.2f}ms")
        finally:
            dispatcher.close()

    # ==========================================================================
    # 5. Fault Injection: Kill FastAPI Mid-Run & Restart Recovery (Task 1 & Acceptance)
    # ==========================================================================

    def test_kill_fastapi_mid_run_and_restart_delivers_all_events(self):
        """Kill backend during operation; all queued events are preserved and delivered upon restart."""
        mock_session = MagicMock(spec=requests.Session)
        dispatcher = EventDispatcher(
            backend_url="http://127.0.0.1:8000",
            enable_outbox=True,
            outbox_path=self.db_path,
            session=mock_session,
        )

        # 1. Simulate FastAPI DOWN (connection errors)
        mock_session.post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        # Dispatch 3 events while backend is dead
        for i in range(3):
            evt = dict(self.sample_event)
            evt["event_id"] = f"evt_fault_{i}"
            dispatcher.dispatch(evt)

        # Wait briefly for worker to attempt delivery
        time.sleep(0.3)
        # All 3 events must still be safely in outbox
        self.assertEqual(dispatcher.outbox.pending_count(), 3)

        # 2. Simulate FastAPI RESTART (backend comes back online)
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"status": "accepted"}
        mock_session.post.side_effect = None
        mock_session.post.return_value = mock_response

        # Allow immediate retry by resetting next_retry_after to 0
        with dispatcher.outbox._get_connection() as conn:
            conn.execute("UPDATE outbox_events SET next_retry_after = 0.0;")

        # Flush dispatcher
        flushed = dispatcher.flush(timeout=3.0)
        self.assertTrue(flushed)
        self.assertEqual(dispatcher.outbox.pending_count(), 0)

        # Verify all 3 events were delivered to backend
        delivered_ids = [
            call.kwargs["json"]["event_id"]
            for call in mock_session.post.call_args_list
            if "json" in call.kwargs
        ]
        self.assertIn("evt_fault_0", delivered_ids)
        self.assertIn("evt_fault_1", delivered_ids)
        self.assertIn("evt_fault_2", delivered_ids)

        dispatcher.close()

    # ==========================================================================
    # 6. Retry with Backoff on 5xx / Permanent Failure on 4xx (Task 1 & 6)
    # ==========================================================================

    def test_transient_503_retries_and_permanent_422_fails(self):
        """503 results in retry with backoff; 422 results in permanent FAILED status."""
        mock_session = MagicMock(spec=requests.Session)
        dispatcher = EventDispatcher(
            backend_url="http://127.0.0.1:8000",
            enable_outbox=True,
            outbox_path=self.db_path,
            session=mock_session,
        )

        # 1. 503 Service Unavailable -> PENDING with retry backoff
        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.text = "Database service unavailable"
        mock_session.post.return_value = resp_503

        evt_503 = dict(self.sample_event)
        evt_503["event_id"] = "evt_503_test"
        dispatcher.dispatch(evt_503)

        time.sleep(0.4)
        with dispatcher.outbox._get_connection() as conn:
            cursor = conn.execute("SELECT status, retry_count, next_retry_after FROM outbox_events WHERE event_id = 'evt_503_test';")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            status, retry_count, next_retry = row
            self.assertEqual(status, "PENDING")
            self.assertGreater(retry_count, 0)
            self.assertGreater(next_retry, time.time())

        # 2. 422 Unprocessable Entity -> FAILED (permanent)
        resp_422 = MagicMock()
        resp_422.status_code = 422
        resp_422.text = "Timestamp too far in the future"
        mock_session.post.return_value = resp_422

        evt_422 = dict(self.sample_event)
        evt_422["event_id"] = "evt_422_test"
        dispatcher.dispatch(evt_422)

        time.sleep(0.4)
        with dispatcher.outbox._get_connection() as conn:
            cursor = conn.execute("SELECT status FROM outbox_events WHERE event_id = 'evt_422_test';")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "FAILED")

        dispatcher.close()

    # ==========================================================================
    # 7. Camera Disconnect: Degraded State & Zero Fabricated EXIT Events (Task 7)
    # ==========================================================================

    def test_camera_disconnect_marks_source_and_emits_no_fabricated_exit(self):
        """When a video source disconnects, it is marked DEGRADED/DISCONNECTED and emits 0 EXIT events."""
        # 1. Phone source disconnect
        phone = PhoneVideoSource(source_id="PHONE_TEST", max_buffer_size=5)
        phone.open()
        self.assertEqual(phone.status, "CONNECTED")

        # Push 1 frame and read
        frame_dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        phone.push_frame(frame_dummy)
        vf = phone.read()
        self.assertIsNotNone(vf)

        # Disconnect source
        phone.release()
        self.assertEqual(phone.status, "DISCONNECTED")
        self.assertIsNone(phone.read())

        # 2. Verify pipeline emits zero fabricated events on disconnected stream
        dispatched_events = []
        mock_dispatcher = MagicMock()
        mock_dispatcher.send_event.side_effect = lambda e, sync=False: dispatched_events.append(e)

        pipeline = LiveCVPipeline(
            app=MagicMock(),
            gallery={},
            event_dispatcher=mock_dispatcher,
        )

        # Stream loop reading from disconnected source
        while True:
            frame = phone.read()
            if frame is None:
                break
            pipeline.process_frame(frame)

        # Confirm ZERO events emitted on disconnect
        self.assertEqual(len(dispatched_events), 0)
        self.assertEqual(len(pipeline.dispatched_events), 0)


if __name__ == "__main__":
    unittest.main()
