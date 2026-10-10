"""Run progress across slow reads, executor threads, corruption and restarts."""
import asyncio
import json
import threading
from unittest.mock import patch

import test_export
from ha_pruefexport.exporter import Builder, ExportFailure, create_export
from ha_pruefexport.progress import ProgressReporter


class ProgressTests(test_export.unittest.TestCase):
    def setUp(self):
        self.fixture = test_export.ExportTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_processed_files_and_stages_are_reported_before_publication(self):
        self.fixture.write("secrets.yaml", "api: progress_sensitive_value_123\n")
        self.fixture.write("a.yaml", "value: progress_sensitive_value_123\n")
        events = []
        builder = Builder(self.fixture.root, self.fixture.root / ".ha_pruefexport",
                          self.fixture.snapshot, "methode", progress=events.append)
        result = builder.build()
        self.assertTrue((builder.private / result["filename"]).is_file())
        self.assertEqual([p["progress_pct"] for p in events], sorted(p["progress_pct"] for p in events))
        self.assertLess(max(p["progress_pct"] for p in events), 100)
        self.assertEqual(events[-1]["phase"], "ZIP freigeben")
        masked = [p for p in events if p["phase"] == "Quelldateien maskieren"]
        self.assertEqual(masked[-1]["processed"], len(builder.contents))
        self.assertEqual(masked[-1]["total"], len(builder.contents))
        self.assertNotIn("progress_sensitive_value_123", json.dumps(events))
        self.assertNotIn(str(self.fixture.root), json.dumps(events))

    def test_crc_verification_rejects_corruption_and_removes_temporary_zip(self):
        changed = False
        def corrupt(event):
            nonlocal changed
            if event["phase"] != "ZIP prüfen" or changed:
                return
            changed = True
            path = next((self.fixture.root / ".ha_pruefexport").glob("*.tmp"))
            with test_export.zipfile.ZipFile(path) as archive:
                member = next(i for i in archive.infolist() if i.compress_size > 0)
            with path.open("r+b") as handle:
                handle.seek(member.header_offset + 26)
                lengths = handle.read(4)
                name_length = int.from_bytes(lengths[:2], "little")
                extra_length = int.from_bytes(lengths[2:], "little")
                handle.seek(member.header_offset + 30 + name_length + extra_length)
                handle.write(b"\xff")  # reserved DEFLATE block type
        with self.assertRaises(ExportFailure) as caught:
            create_export(self.fixture.root, self.fixture.root / ".ha_pruefexport",
                          self.fixture.snapshot, "methode", progress=corrupt)
        self.assertTrue(changed)
        self.assertEqual(caught.exception.details["phase"], "ZIP prüfen")
        self.assertEqual(list((self.fixture.root / ".ha_pruefexport").iterdir()), [])

    def test_repeated_counts_are_throttled_and_percentages_never_regress(self):
        events = []
        reporter = ProgressReporter(events.append)
        with patch("ha_pruefexport.progress.time.monotonic", return_value=10):
            reporter("Dateien lesen", 30, 1)
            for count in range(2, 1000):
                reporter("Dateien lesen", 30, count)
            reporter("Dateien maskieren", 50, 0, 5)
            reporter("Dateien maskieren", 40, 1, 5)
            reporter("ZIP prüfen", 150)
        self.assertEqual(len(events), 3)
        self.assertEqual([p["progress_pct"] for p in events], [30, 50, 99])


class ManagerProgressTests(test_export.unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = test_export.ManagerTests()
        await self.fixture.asyncSetUp()
        self.manager = self.fixture.manager

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    async def test_heartbeat_during_a_slow_read_does_not_invent_progress(self):
        entered, release, heartbeat_seen = asyncio.Event(), asyncio.Event(), asyncio.Event()
        baseline, threads = {}, []
        main_thread = threading.get_ident()
        async def slow(hass, progress=None):
            progress({"phase": "Wetter und Kalender lesen", "progress_pct": 20, "processed": 0, "total": 3, "unit": "Abrufe"})
            entered.set()
            await release.wait()
            return {"files": {}, "issues": [], "local_references": []}
        def observe():
            threads.append(threading.get_ident())
            if baseline and self.manager.status["heartbeat_at"] != baseline["heartbeat"]:
                heartbeat_seen.set()
        self.manager.subscribe(observe)
        with patch("ha_pruefexport.manager.collect", slow), patch("ha_pruefexport.manager.HEARTBEAT_SECONDS", 0.01):
            self.assertTrue(self.manager.start("methode"))
            await asyncio.wait_for(entered.wait(), 2)
            baseline.update(heartbeat=self.manager.status["heartbeat_at"], progress=self.manager.status["last_progress_at"])
            try:
                await asyncio.wait_for(heartbeat_seen.wait(), 2)
                self.assertEqual(self.manager.attributes()["progress_pct"], 20)
                self.assertEqual(self.manager.status["last_progress_at"], baseline["progress"])
                self.assertTrue(self.manager.attributes()["running"])
                self.assertEqual(self.manager.attributes()["processed"], 0)
            finally:
                release.set()
                await self.manager.task
        self.assertTrue(all(thread == main_thread for thread in threads))
        self.assertEqual(self.manager.attributes()["progress_pct"], 100)
        self.assertFalse(self.manager.attributes()["running"])

    async def test_completion_failure_and_new_run_reset_are_distinct(self):
        events = []
        def observe():
            attributes = self.manager.attributes()
            events.append(attributes)
            if attributes["progress_pct"] == 100:
                self.assertTrue(attributes["has_archive"])
                self.assertTrue(self.manager.archive_path(attributes["archive_name"]).is_file())
        self.manager.subscribe(observe)
        async def snapshot(hass, progress=None):
            return {"files": {}, "issues": [], "local_references": []}
        with patch("ha_pruefexport.manager.collect", snapshot):
            self.manager.start("methode")
            await self.manager.task
        self.assertEqual(events[0]["progress_pct"], 0)
        self.assertEqual(events[-1]["progress_pct"], 100)
        self.assertEqual([e["progress_pct"] for e in events], sorted(e["progress_pct"] for e in events))
        filename = self.manager.attributes()["archive_name"]
        async def fail(hass, progress=None):
            raise ValueError("synthetic failure")
        with patch("ha_pruefexport.manager.collect", fail), self.assertLogs("ha_pruefexport.manager", level="ERROR"):
            self.manager.start("methode")
            self.assertEqual(self.manager.attributes()["progress_pct"], 0)
            await self.manager.task
        self.assertEqual(self.manager.status["state"], "fehler")
        self.assertLess(self.manager.attributes()["progress_pct"], 100)
        self.assertEqual(self.manager.attributes()["archive_name"], filename)
        self.assertFalse(self.manager.attributes()["running"])

    async def test_stale_progress_and_cancellation_cannot_complete_a_new_run(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(hass, progress=None):
            entered.set()
            await release.wait()
            return {"files": {}, "issues": [], "local_references": []}
        with patch("ha_pruefexport.manager.collect", slow):
            self.manager.start("methode")
            await asyncio.wait_for(entered.wait(), 2)
            self.manager.update_progress(self.manager.run_serial - 1, {"phase": "Veraltete Meldung", "progress_pct": 99})
            self.assertEqual(self.manager.attributes()["progress_pct"], 0)
            self.assertNotEqual(self.manager.attributes()["phase"], "Veraltete Meldung")
            await self.manager.async_stop()
        self.assertEqual(self.manager.status["state"], "fehler")
        self.assertFalse(self.manager.attributes()["running"])
        self.assertLess(self.manager.attributes()["progress_pct"], 100)
        self.assertFalse(self.manager.attributes()["has_archive"])
