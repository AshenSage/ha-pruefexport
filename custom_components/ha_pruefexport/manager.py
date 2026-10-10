"""Background job, persisted status, and retention of three completed archives."""
import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .collect import collect
from .const import DOWNLOAD_PREFIX, PRIVATE_DIR, STATES, VERSION
from .exporter import ARCHIVE_RE, ExportCancelled, ExportFailure, create_export, failure_details, utcnow

_LOGGER = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 2


class ExportManager:
    def __init__(self, hass):
        self.hass = hass
        self.root = Path(hass.config.path())
        self.private = self.root / PRIVATE_DIR
        self.status = {"state": "bereit", "phase": None, "last_started": None,
                       "last_finished": None, "last_success": None, "last_error": None,
                       "last_error_details": None, "archive": None,
                       "progress_pct": None, "processed": None, "total": None, "unit": None,
                       "heartbeat_at": None, "last_progress_at": None, "elapsed_seconds": None}
        self.listeners = set()
        self.task = None
        self.cancel = threading.Event()
        self.worker = None
        self.archive_available = False
        self.run_serial = 0
        self.started_monotonic = None

    async def async_load(self):
        def load():
            if self.private.is_symlink():
                raise ValueError("symlink")
            self.private.mkdir(mode=0o700, exist_ok=True)
            path = self.private / "status.json"
            if path.is_symlink():
                raise ValueError("symlink")
            for temporary in self.private.glob("*.tmp"):
                if temporary.is_file() and not temporary.is_symlink():
                    temporary.unlink()
            if path.exists():
                if path.stat().st_size > 16384:
                    raise ValueError("status limit")
                return json.loads(path.read_text())
            return None
        try:
            stored = await self.hass.async_add_executor_job(load)
            if isinstance(stored, dict) and stored.get("state") in STATES:
                self.status.update({k: stored.get(k) for k in self.status})
            archive = self.status.get("archive")
            self.archive_available = bool(archive and await self.hass.async_add_executor_job(self.archive_path, archive.get("filename")))
            if archive and not self.archive_available:
                self.status.update(state="fehler", archive=None, last_error="Letztes Archiv fehlt oder ist nicht zugänglich")
            if self.status["state"] == "laeuft":
                self.status.update(state="fehler", phase=None, progress_pct=None, heartbeat_at=None,
                                   last_error="Export durch Neustart unterbrochen")
        except Exception:
            self.status.update(state="fehler", last_error="Exportstatus nicht lesbar")

    @callback
    def notify(self):
        for listener in list(self.listeners):
            listener()

    @callback
    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    def archive_path(self, name):
        if not isinstance(name, str) or not ARCHIVE_RE.fullmatch(name) or self.private.is_symlink():
            return None
        path = self.private / name
        return path if path.is_file() and not path.is_symlink() else None

    def attributes(self):
        archive = self.status.get("archive") or {}
        running = self.status["state"] == "laeuft"
        return {"phase": self.status.get("phase"), "running": running, "exporter_version": VERSION,
                "progress_pct": self.status.get("progress_pct"), "processed": self.status.get("processed"),
                "total": self.status.get("total"), "unit": self.status.get("unit"),
                "heartbeat_at": self.status.get("heartbeat_at"), "last_progress_at": self.status.get("last_progress_at"),
                "elapsed_seconds": self.elapsed() if running else self.status.get("elapsed_seconds"),
                "last_started": self.status.get("last_started"),
                "last_finished": self.status.get("last_finished"), "last_success": self.status.get("last_success"),
                "last_error": self.status.get("last_error"), "has_archive": self.archive_available,
                "last_error_details": self.status.get("last_error_details"),
                "archive_name": archive.get("filename"), "archive_bytes": archive.get("bytes"),
                "archive_finished": archive.get("finished"), "archive_status": archive.get("status"),
                "archive_files": archive.get("files"), "archive_sources": archive.get("sources"),
                "archive_issues": archive.get("issues"), "archive_maskierungen": archive.get("maskierungen"),
                "pruefmodus": archive.get("mode"),
                "download_path": DOWNLOAD_PREFIX + archive["filename"] if self.archive_available else None}

    def elapsed(self):
        return max(0, int(time.monotonic() - self.started_monotonic)) if self.started_monotonic is not None else None

    @callback
    def update_progress(self, run_serial, event):
        if run_serial != self.run_serial or self.status["state"] != "laeuft":
            return
        value = max(self.status.get("progress_pct") or 0, min(99, event["progress_pct"]))
        changed = any(self.status.get(key) != event.get(key) for key in ("phase", "processed", "total", "unit")) or value != self.status.get("progress_pct")
        self.status.update({key: event.get(key) for key in ("phase", "processed", "total", "unit")})
        self.status.update(progress_pct=value, heartbeat_at=utcnow())
        if changed:
            self.status["last_progress_at"] = self.status["heartbeat_at"]
        self.notify()

    async def heartbeat(self, run_serial):
        while run_serial == self.run_serial and self.status["state"] == "laeuft":
            await asyncio.sleep(HEARTBEAT_SECONDS)
            if run_serial == self.run_serial and self.status["state"] == "laeuft":
                self.status["heartbeat_at"] = utcnow()
                self.notify()

    async def save(self):
        data = json.dumps(self.status, ensure_ascii=False, indent=2)
        def write():
            if self.private.is_symlink():
                raise ValueError("symlink")
            target = self.private / "status.json"
            temporary = self.private / "status.json.tmp"
            if target.is_symlink() or temporary.is_symlink():
                raise ValueError("symlink")
            temporary.write_text(data, encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        await self.hass.async_add_executor_job(write)

    @callback
    def start(self, mode="gesamt"):
        if mode not in {"methode", "gesamt"}:
            raise HomeAssistantError("pruefmodus muss methode oder gesamt sein")
        if self.task is not None and not self.task.done():
            # Repeated taps observe the same run rather than reporting a failure.
            self.notify()
            return False
        self.cancel.clear()
        self.run_serial += 1
        self.started_monotonic = time.monotonic()
        started = utcnow()
        self.status.update(state="laeuft", phase="Export starten", last_started=started,
                           progress_pct=0, processed=None, total=None, unit=None,
                           heartbeat_at=started, last_progress_at=started, elapsed_seconds=0,
                           last_error=None, last_error_details=None)
        self.task = self.hass.async_create_background_task(self.run("gesamt"), "HA Prüfexport")
        self.notify()
        return True

    async def run(self, mode):
        phase = "Exportstatus speichern"
        run_serial = self.run_serial
        loop = asyncio.get_running_loop()
        heartbeat = asyncio.create_task(self.heartbeat(run_serial))
        def progress(event):
            # File progress originates in an executor thread. Entity updates are
            # always dispatched onto Home Assistant's event loop.
            loop.call_soon_threadsafe(self.update_progress, run_serial, event)
        try:
            await self.save()
            phase = "HA-Daten sammeln"
            snapshot = await collect(self.hass, progress=progress)
            phase = "Dateien und ZIP erstellen"
            self.worker = asyncio.ensure_future(self.hass.async_add_executor_job(create_export, self.root, self.private, snapshot, mode, self.cancel, progress))
            result = await asyncio.shield(self.worker)
            self.update_progress(run_serial, {"phase": "Export abschliessen", "progress_pct": 99})
            phase = "Alte Archive aufräumen"
            await self.hass.async_add_executor_job(self.prune, result["filename"])
            self.status.update(state=result["status"], phase=None, last_finished=result["finished"],
                               last_success=result["finished"], archive=result, last_error=None, last_error_details=None,
                               progress_pct=100, processed=None, total=None, unit=None,
                               elapsed_seconds=self.elapsed(), heartbeat_at=utcnow())
            self.archive_available = True
            phase = "Exportstatus speichern"
            await self.save()
        except (asyncio.CancelledError, ExportCancelled):
            self.cancel.set()
            if self.worker is not None and not self.worker.done():
                try:
                    await self.worker
                except (ExportCancelled, Exception):
                    pass
            self.status.update(state="fehler", phase=None, last_finished=utcnow(), last_error="Export unterbrochen",
                               elapsed_seconds=self.elapsed(), progress_pct=min(self.status.get("progress_pct") or 0, 99))
            try:
                await self.save()
            except Exception:
                pass
        except Exception as error:
            details = error.details if isinstance(error, ExportFailure) else failure_details(error, phase)
            message = "Export fehlgeschlagen · " + details["phase"] + " · " + details["fehlerart"] + " · " + details["stelle"]
            if details.get("pruefbereich"):
                message += " · " + details["pruefbereich"] + " · ID " + details["datei_id"]
            # No raw message, URL, traceback source line or credentials in the log.
            _LOGGER.error("HA Prüfexport abgebrochen: %s", json.dumps(details, ensure_ascii=False))
            self.status.update(state="fehler", phase=None, last_finished=utcnow(),
                               last_error=message, last_error_details=details,
                               elapsed_seconds=self.elapsed(), progress_pct=min(self.status.get("progress_pct") or 0, 99))
            try:
                await self.save()
            except Exception:
                pass
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            self.worker = None
            self.notify()

    def prune(self, current=None):
        completed = sorted((p for p in self.private.glob("ha_pruefexport_*.zip") if self.archive_path(p.name)),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        current = current or (self.status.get("archive") or {}).get("filename")
        others = [p for p in completed if p.name != current]
        keep = ({current} if current else set()) | {p.name for p in others[:2 if current else 3]}
        for path in completed:
            if path.name not in keep:
                path.unlink()

    async def async_stop(self):
        self.cancel.set()
        if self.task is not None and not self.task.done():
            # Cancel HA reads promptly; the file worker notices the same Event.
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
