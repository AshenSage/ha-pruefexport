"""Bounded, read-only source collector. No HA imports; also usable in offline tests."""
from __future__ import annotations

import hashlib
import gzip
import json
import math
import os
import re
import stat
import threading
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import yaml

from .const import VERSION

FORMAT_VERSION = 1
MAX_FILE = 12 * 1024 * 1024
MAX_TOTAL = 80 * 1024 * 1024
MAX_ENTRIES = 100000
MASK = "[MASKIERT]"
# These paths and the manifest schema are fixed exporter labels, not source data.
GENERATED_PATHS = {"inventar/secrets_nur_namen.json", "inventar/abhaengigkeiten.json",
                   "inventar/dateien.json", "inventar/dateiliste.txt", "KONTEXT.md",
                   "PRUEFAUFTRAG.md", "EXPORTBERICHT.md", "manifest.json"}
TEXT_EXT = {".yaml", ".yml", ".json", ".py", ".sh", ".js", ".mjs", ".css",
            ".jinja", ".jinja2", ".j2", ".md", ".toml", ".txt", ".html", ".svg", ".conf", ".ini"}
SKIP_DIR = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
ROOT_SKIP_DIR = {".ha_pruefexport", "backups", "backup", "media", "tts", ".cloud", ".cache"}
KNOWN_NON_SOURCE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".bmp",
                        ".mp4", ".mkv", ".mov", ".mp3", ".wav", ".ogg", ".flac", ".ttf",
                        ".woff", ".woff2", ".eot", ".map"}
KNOWN_NON_SOURCE_NAMES = {".HA_VERSION", ".ha_run.lock", "home-assistant.log.fault"}
CONNECTLIFE_BUTTON_KEYS = {"cancel", "light_off", "light_on", "pause", "resume", "start", "stop", "stop_add_go"}
STORAGE_ALLOWED = {"core.config", "core.restore_state", "core.config_entries",
                   "core.entity_registry", "core.device_registry", "core.area_registry",
                   "core.floor_registry", "core.label_registry", "core.category_registry",
                   "energy", "trace.saved_traces", "frontend.user_data", "lovelace_resources"}
HELPERS = {"input_boolean", "input_button", "input_datetime", "input_number", "input_select",
           "input_text", "timer", "counter", "schedule", "person", "zone", "tag"}
SECRET_KEY = re.compile(r"(?i)^(?:.*(?:password|passwd|passphrase|private_key|client_secret|"
                        r"access_token|refresh_token|api_key|apikey|auth_token|encryption_key|"
                        r"webhook_id|alarm_code|pincode|pin_code|_token)|token|authorization|credentials|"
                        r"secret|pin|access_code|authsig|cookie|session_id|key)$")
ARCHIVE_RE = re.compile(r"^ha_pruefexport_\d{8}_\d{6}_[a-f0-9]{8}\.zip$")
OLD_EXPORT_DIR_RE = re.compile(r"^ha_pruefung_\d{8}_\d{6}$")
ASSIGN = re.compile(r'''(?im)(["']?(?:password|passwd|passphrase|api_key|apikey|access_token|refresh_token|token|client_secret|authorization|alarm_code|pin|private_key)["']?\s*[:=]\s*)(["'])([^\r\n]*?)\2''')
BARE_ASSIGN = re.compile(r"(?im)^(\s*(?:export\s+)?(?:password|passwd|api_key|apikey|access_token|refresh_token|token|client_secret|alarm_code|pin)\s*=\s*)([a-zA-Z0-9_./+~-]+)(\s*(?:#.*)?)$")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def storage_allowed(name):
    return name in STORAGE_ALLOWED or name.split(".")[0] in HELPERS or name in {"lovelace", "lovelace_dashboards"} or name.startswith(("lovelace.", "frontend.user_data_"))


def is_secret_key(key):
    normalized = re.sub(r"([a-z])([A-Z])", r"\1_\2", str(key)).replace("-", "_").replace(" ", "_")
    return bool(SECRET_KEY.fullmatch(normalized))


def storage_metadata_key(value, path):
    """Only a verified HA storage envelope's own key is public format metadata."""
    if (str(path).startswith(".storage/") and isinstance(value, dict)
            and type(value.get("version")) is int and type(value.get("minor_version")) is int
            and "data" in value and isinstance(value["data"], (dict, list))
            and value.get("key") == str(path)[len(".storage/"):]):
        return value["key"]
    return None


class Redactor:
    def __init__(self):
        self.known = set()
        self.count = 0
        self.secret_names = set()
        self.redacted_keys = 0

    def remember(self, value):
        if isinstance(value, str) and len(value) >= 8 and not self.expression(value):
            self.known.add(value)
            self.known.add(quote(value, safe=""))
            self.known.add(json.dumps(value, ensure_ascii=False)[1:-1])

    @staticmethod
    def expression(value):
        return isinstance(value, str) and ("{{" in value or "{%" in value or value.strip().startswith("!secret "))

    def learn(self, value, metadata_key=None):
        if isinstance(value, dict):
            for key, item in value.items():
                public_storage_key = key == "key" and metadata_key is not None and item == metadata_key
                if is_secret_key(key) and not public_storage_key and isinstance(item, (str, int)):
                    self.remember(item)
                self.learn(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.learn(item)

    def mask(self):
        self.count += 1
        return self.marker

    @property
    def marker(self):
        # A known value may be MASKIERT itself. The fallback is shorter than the
        # minimum remembered literal, so replacing a value cannot recreate it.
        return "[MASK]" if self.contains_known(MASK) else MASK

    def contains_known(self, value):
        return any(literal in value for literal in self.known)

    def text(self, value):
        value = re.sub(r"-----BEGIN (?:[A-Z ]* )?PRIVATE KEY-----.*?-----END (?:[A-Z ]* )?PRIVATE KEY-----",
                       lambda m: self.mask(), value, flags=re.S)
        value = re.sub(r"(?i)(Bearer\s+)[a-z0-9._~+/=-]+", lambda m: m[1] + self.mask(), value)
        value = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/<>\"']+:[^\s/@<>\"']+@", lambda m: m[1] + self.mask() + "@", value)
        value = re.sub(r"(?i)([?&](?:token|access_token|accessToken|api_key|apikey|password|authSig|key)=)[^\s&#\"']+",
                       lambda m: m[1] + self.mask(), value)
        for literal in sorted(self.known, key=len, reverse=True):
            if literal and literal in value:
                self.count += value.count(literal)
                value = value.replace(literal, self.marker)
        return value

    def object(self, value, path="", metadata_key=None):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                key = str(key)
                exported_key = self.text(key)
                if exported_key != key:
                    self.redacted_keys += 1
                # Redaction can make distinct keys identical. Preserve every value.
                base = exported_key
                suffix = 2
                while exported_key in out:
                    exported_key = base + "__" + str(suffix)
                    suffix += 1
                if key == "state" and str(value.get("entity_id", "")).startswith("input_text."):
                    out[exported_key] = self.mask()
                elif key == "initial" and "input_text" in path:
                    out[exported_key] = self.mask() if item is not None else None
                elif key == "key" and metadata_key is not None and item == metadata_key:
                    out[exported_key] = self.text(item)
                elif is_secret_key(key) and item is not None and not isinstance(item, (dict, list)) and not self.expression(item):
                    out[exported_key] = self.mask()
                else:
                    out[exported_key] = self.object(item, path + "/" + key)
            return out
        if isinstance(value, (list, tuple, set)):
            return [self.object(v, path) for v in value]
        if isinstance(value, str):
            if path.startswith("diagnose/system_log.json/"):
                # Log messages are unstructured: learn and mask quoted assignments
                # and plain key=value fields before the completed literal sweep.
                value = self.source(value, ".txt")
                def log_assignment(match):
                    self.remember(match[2])
                    return match[1] + self.mask()
                value = re.sub(r"(?i)(\b(?:password|passwd|api_key|apikey|access_token|refresh_token|client_secret|alarm_code|pin)\s*[:=]\s*)([a-zA-Z0-9_./+~=-]+)", log_assignment, value)
            return self.text(value)
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else {"nicht_exportierbar": "nicht endlicher Zahlenwert"}
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "as_dict"):
            return self.object(value.as_dict(), path)
        return {"nicht_exportierbar": "Datentyp " + type(value).__name__}

    def yaml(self, source, source_path=""):
        root = yaml.compose(source)
        changes = []
        visited = set()
        public_keys = set()
        # ConnectLife ships declarative button identifiers named "key". This
        # narrow exception never applies to generic keys, unknown identifiers,
        # credentials, or values learned as secrets elsewhere.
        if re.fullmatch(r"custom_components/connectlife/data_dictionaries/[a-zA-Z0-9_-]+\.ya?ml", source_path) and isinstance(root, yaml.MappingNode):
            for field, buttons in root.value:
                if field.value != "buttons" or not isinstance(buttons, yaml.SequenceNode):
                    continue
                for button in buttons.value:
                    if not isinstance(button, yaml.MappingNode):
                        continue
                    fields = {k.value: v for k, v in button.value}
                    key_node = fields.get("key")
                    if isinstance(key_node, yaml.ScalarNode) and key_node.tag == "tag:yaml.org,2002:str" and key_node.value in CONNECTLIFE_BUTTON_KEYS and isinstance(fields.get("write"), yaml.MappingNode):
                        public_keys.add(id(key_node))

        def walk(node, key=None, path=""):
            if node is None or id(node) in visited:
                return
            visited.add(id(node))
            if isinstance(node, yaml.ScalarNode):
                if node.tag == "!secret":
                    self.secret_names.add(node.value)
                if id(node) not in public_keys and node.tag != "!secret" and is_secret_key(key or "") and node.tag != "tag:yaml.org,2002:null" and not self.expression(node.value):
                    self.remember(node.value)
                    changes.append((node.start_mark.index, node.end_mark.index, json.dumps(self.mask())))
                elif node.tag != "!secret" and key == "initial" and "/input_text/" in path:
                    # Deliberately cautious: input_text may contain a PIN or private plate.
                    changes.append((node.start_mark.index, node.end_mark.index, json.dumps(self.mask())))
                else:
                    redacted = self.text(node.value)
                    if redacted != node.value:
                        tag = node.tag + " " if node.tag.startswith("!") else ""
                        changes.append((node.start_mark.index, node.end_mark.index, tag + json.dumps(redacted, ensure_ascii=False)))
            elif isinstance(node, yaml.MappingNode):
                for k, val in node.value:
                    walk(k, None, path)
                    walk(val, k.value, path + "/" + str(k.value) + "/")
            elif isinstance(node, yaml.SequenceNode):
                for val in node.value:
                    walk(val, key, path)
        walk(root)
        for start, end, replacement in sorted(changes, reverse=True):
            source = source[:start] + replacement + source[end:]
        source = self.text(source)
        # Replacing an anchor or another non-scalar part may be unsafe. Omit that
        # source with an explicit gap rather than shipping syntactically broken YAML.
        yaml.compose(source)
        return source

    def source(self, source, extension, path=""):
        if extension in {".yaml", ".yml"}:
            return self.yaml(source, path)
        if extension == ".json":
            raw = json.loads(source)
            metadata_key = storage_metadata_key(raw, path)
            self.learn(raw, metadata_key)
            return dump_json(self.object(raw, path, metadata_key)).decode()
        # Mask literal assignments, preserve code expressions such as token = template(...).
        def assignment(match):
            if self.expression(match[3]):
                return match[0]
            self.remember(match[3])
            return match[1] + match[2] + self.mask() + match[2]
        source = ASSIGN.sub(assignment, source)
        if extension in {".sh", ".conf", ".ini", ".txt"}:
            def bare(match):
                if match[2].startswith("$"):
                    return match[0]
                self.remember(match[2])
                return match[1] + '"' + self.mask() + '"' + match[3]
            source = BARE_ASSIGN.sub(bare, source)
        elif extension == ".py":
            source = re.sub(r"(?im)^(\s*(?:pin|alarm_code)\s*=\s*)\d+(\s*(?:#.*)?)$", lambda m: m[1] + '"' + self.mask() + '"' + m[2], source)
        return self.text(source)


class ExportCancelled(Exception):
    pass


class MaskingCheckError(ValueError):
    def __init__(self, area, name):
        # Never retain the matched value or raw source filename in the error.
        self.area = area
        self.file_id = digest(name.encode("utf-8"))[:12]
        super().__init__("Maskierungskontrolle fehlgeschlagen; Archiv nicht veröffentlicht")


def failure_details(error, phase):
    """Describe the location without serializing an exception message or source line."""
    frames = []
    for frame, lineno in traceback.walk_tb(error.__traceback__):
        name = Path(frame.f_code.co_filename).name
        if name in {"manager.py", "collect.py", "exporter.py"}:
            frames.append(name + ":" + str(lineno))
    details = {"phase": phase, "fehlerart": type(error).__name__,
               "stelle": frames[-1] if frames else "nicht ermittelt", "exporter_frames": frames}
    if isinstance(error, MaskingCheckError):
        details.update(pruefbereich=error.area, datei_id=error.file_id)
    return details


class ExportFailure(ValueError):
    """Safe context from the background worker, with no original message attached."""
    def __init__(self, details):
        self.details = details
        super().__init__("Export fehlgeschlagen · " + details["phase"] + " · " +
                         details["fehlerart"] + " · " + details["stelle"])


class Builder:
    def __init__(self, root, private, snapshot, mode="gesamt", cancel=None, limits=None, progress=None):
        self.root = Path(root).resolve()
        self.private = Path(private)
        self.snapshot = snapshot
        # Old callers may still pass "methode"; every new archive is a full audit.
        self.mode = "gesamt"
        self.cancel = cancel or threading.Event()
        self.max_file, self.max_total, self.max_entries = limits or (MAX_FILE, MAX_TOTAL, MAX_ENTRIES)
        self.redactor = Redactor()
        self.inventory = []
        self.issues = list(snapshot.get("issues", []))
        self.dependencies = []
        self.payload = {}
        self.total = 0
        self.refs = {"configuration.yaml"}
        self.secret_present = set()
        self.nodes = {}
        self.contents = {}
        self.read_total = 0
        self.phase = "Exportverzeichnis vorbereiten"
        self.archive_names = {}
        self.allocated_names = set(GENERATED_PATHS)
        self.renamed_paths = 0
        from .progress import ProgressReporter
        self.progress = ProgressReporter(progress)

    def report(self, phase, percent, processed=None, total=None, unit=None):
        self.phase = phase
        self.progress(phase, percent, processed, total, unit)

    def check(self):
        if self.cancel.is_set():
            raise ExportCancelled()

    def issue(self, component, status, detail):
        self.issues.append({"bereich": component, "status": status, "grund": self.redactor.text(detail)})

    def archive_name(self, name):
        if name in self.archive_names:
            return self.archive_names[name]
        if name in GENERATED_PATHS:
            return name
        base = self.redactor.text(name)
        result = base
        suffix = 2
        while result in self.allocated_names:
            result = base + "__" + str(suffix)
            suffix += 1
        self.archive_names[name] = result
        self.allocated_names.add(result)
        self.renamed_paths += result != name
        return result

    def archive_references(self, value):
        if isinstance(value, dict):
            return {key: self.archive_names.get(item, item)
                    if key == "archivpfad" and isinstance(item, str)
                    else self.archive_references(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.archive_references(item) for item in value]
        return value

    def add(self, name, data, critical=True):
        self.check()
        if len(data) > self.max_file or self.total + len(data) > self.max_total:
            self.issue(name, "teilweise" if critical else "ausgelassen", "Datei-/Gesamtlimit erreicht")
            return False
        self.payload[self.archive_name(name)] = data
        self.total += len(data)
        return True

    def read_secrets(self):
        path = self.root / "secrets.yaml"
        if not path.exists() or path.is_symlink():
            return
        try:
            if path.stat().st_size > self.max_file:
                self.issue("secrets", "teilweise", "Secret-Abgleich wegen Grössenlimit nicht möglich")
                return
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                self.secret_present = set(map(str, raw))
                for value in raw.values():
                    self.redactor.remember(value)
        except (OSError, ValueError, yaml.YAMLError):
            self.issue("secrets", "teilweise", "Secrets lokal nicht lesbar; Inhalte bleiben ausgelassen")

    def inventory_files(self):
        count = 0
        def inaccessible(error):
            path = str(getattr(error, "filename", "unbekannt"))
            try:
                path = Path(path).relative_to(self.root).as_posix()
            except ValueError:
                path = "unbekannt"
            self.inventory.append({"pfad": path + "/", "typ": "verzeichnis", "entscheidung": "fehlgeschlagen", "grund": "Unterbaum nicht lesbar"})
            self.issue("Dateiinventar", "teilweise", "Verzeichnis nicht lesbar: " + path)
        for parent, dirs, files in os.walk(self.root, followlinks=False, onerror=inaccessible):
            self.check()
            dirs.sort()
            files.sort()
            for name in list(dirs):
                p = Path(parent) / name
                rel = p.relative_to(self.root).as_posix()
                at_root = Path(parent) == self.root
                old_export = at_root and bool(OLD_EXPORT_DIR_RE.fullmatch(name))
                if p.is_symlink() or name in SKIP_DIR or (at_root and name in ROOT_SKIP_DIR) or old_export:
                    self.inventory.append({"pfad": rel + "/", "typ": "symlink" if p.is_symlink() else "verzeichnis",
                                           "entscheidung": "ausgelassen", "grund": "Symlink" if p.is_symlink() else
                                           "Früheres Prüfexport-Verzeichnis; Unterbaum nicht inventarisiert" if old_export else
                                           "Cache, Medien, Backup oder Export; Unterbaum nicht inventarisiert"})
                    dirs.remove(name)
            for name in files:
                self.check()
                count += 1
                self.report("Dateien erfassen", 30, count, unit="Dateien geprüft")
                if count > self.max_entries:
                    self.issue("Dateiinventar", "teilweise", "Inventarlimit erreicht; restliche Pfade nicht erfasst")
                    return
                p = Path(parent) / name
                rel = p.relative_to(self.root).as_posix()
                try:
                    s = p.lstat()
                    row = {"pfad": rel, "bytes": s.st_size, "mtime_utc": datetime.fromtimestamp(s.st_mtime, timezone.utc).isoformat(),
                           "rechte": oct(stat.S_IMODE(s.st_mode)), "typ": "datei", "entscheidung": "ausgelassen", "grund": ""}
                    self.inventory.append(row)
                    if not stat.S_ISREG(s.st_mode):
                        row.update(typ="symlink" if p.is_symlink() else "spezial", grund="Keine reguläre Datei; Ziel nicht verfolgt")
                        continue
                    lower = name.lower()
                    if lower.endswith((".js.gz", ".css.gz")):
                        try:
                            if s.st_size > self.max_file:
                                raise ValueError("limit")
                            with gzip.open(p, "rb") as f:
                                unpacked = f.read(self.max_file + 1)
                            plain_path = p.with_suffix("")
                            if len(unpacked) > self.max_file or not plain_path.is_file() or plain_path.is_symlink() or plain_path.stat().st_size > self.max_file:
                                raise ValueError("not comparable")
                            if digest(unpacked) == digest(plain_path.read_bytes()):
                                row["grund"] = "Identische komprimierte Frontend-Kopie; SHA256 des entpackten Inhalts geprüft"
                            else:
                                row["grund"] = "Komprimierter Frontend-Inhalt weicht ab; ausgelieferte Fassung gesondert prüfen"
                                self.issue(rel, "teilweise", row["grund"])
                        except (OSError, EOFError, ValueError):
                            row["grund"] = "Komprimierte Frontend-Kopie nicht sicher vergleichbar"
                            self.issue(rel, "teilweise", row["grund"])
                        continue
                    if lower == "secrets.yaml" or lower.startswith(("auth", "home-assistant_v2.db")) or p.suffix.lower() in {".key", ".pem", ".p12", ".pfx", ".db", ".db-wal", ".zip", ".gz", ".tgz"}:
                        row["grund"] = "Zugangsdaten, Datenbank, Archiv, Schlüssel oder komprimierte Kopie"
                        continue
                    if rel.startswith(".storage/") and not storage_allowed(name):
                        row["grund"] = "Nicht freigegebenes Speicherformat; keine Rohkopie"
                        if not name.startswith(("auth", "http", "onboarding", "analytics", "hacs", "cloud", "mobile_app", "bluetooth", "repairs")):
                            self.issue(rel, "nicht_ausgewertet", "Unbekannte Speicherdatei: zusätzliche Definitionen möglich")
                        continue
                    is_storage = rel.startswith(".storage/")
                    is_log = lower in {"home-assistant.log", "home-assistant.log.1"}
                    if not is_storage and not is_log and p.suffix.lower() not in TEXT_EXT:
                        row["grund"] = "Binärdatei oder nicht unterstütztes Format"
                        if p.suffix.lower() not in KNOWN_NON_SOURCE_EXT and name not in KNOWN_NON_SOURCE_NAMES and not rel.startswith("image/"):
                            self.issue(rel, "nicht_ausgewertet", "Nicht unterstütztes Dateiformat; mögliche zusätzliche Quelle prüfen")
                        continue
                    if s.st_size > self.max_file and not is_log:
                        row["grund"] = "Dateilimit erreicht"
                        self.issue(rel, "teilweise", "Dateilimit erreicht")
                        continue
                    if self.read_total + min(s.st_size, 256 * 1024 if is_log else self.max_file) > self.max_total:
                        row["grund"] = "Gesamtlimit für Quelldateien erreicht"
                        self.issue(rel, "teilweise", row["grund"])
                        continue
                    try:
                        with p.open("rb") as f:
                            if is_log:
                                f.seek(max(0, s.st_size - 256 * 1024))
                            data = f.read(self.max_file + 1)
                        if len(data) > self.max_file:
                            raise ValueError("limit")
                        source = data.decode("utf-8")
                        self.read_total += len(data)
                        ext = ".json" if is_storage else p.suffix.lower()
                        if ext in {".yaml", ".yml"}:
                            self.nodes[rel] = yaml.compose(source)
                            # Learn all literals before processing any other file.
                            self.redactor.yaml(source, rel)
                        elif ext == ".json":
                            raw = json.loads(source)
                            self.redactor.learn(raw, storage_metadata_key(raw, rel))
                        else:
                            for match in ASSIGN.finditer(source):
                                self.redactor.remember(match[3])
                            if ext in {".sh", ".conf", ".ini", ".txt"}:
                                for match in BARE_ASSIGN.finditer(source):
                                    self.redactor.remember(match[2])
                        self.contents[rel] = (source, ext, is_log)
                        row.update(entscheidung="vorgemerkt", grund="", sha256_quelle=digest(data))
                        if is_log and s.st_size > len(data):
                            row["umfang"] = "Letzte 256 KiB; Beginn gegebenenfalls mitten in einer Zeile"
                    except yaml.YAMLError as error:
                        # Never export error text, source snippets or YAML values.
                        row["fehlerart"] = type(error).__name__
                        mark = getattr(error, "problem_mark", None)
                        if mark is not None:
                            row["yaml_zeile"] = mark.line + 1
                            row["yaml_spalte"] = mark.column + 1
                        position = (f" (Zeile {row['yaml_zeile']}, Spalte {row['yaml_spalte']})"
                                    if mark is not None else "")
                        row["grund"] = "Ungültiges YAML" + position + "; Inhalt ausgelassen"
                        self.issue(rel, "teilweise", row["grund"])
                    except (OSError, ValueError, UnicodeError):
                        row["grund"] = "Nicht lesbar oder nicht sicher auswertbar; Inhalt ausgelassen"
                        self.issue(rel, "teilweise", row["grund"])
                except OSError:
                    self.inventory.append({"pfad": rel, "entscheidung": "fehlgeschlagen", "grund": "Dateimetadaten nicht lesbar"})
                    self.issue(rel, "teilweise", "Dateimetadaten nicht lesbar")

    def resolve_ref(self, origin, value, directory=False):
        candidate = Path(value)
        path = candidate if candidate.is_absolute() else self.root / Path(origin).parent / candidate
        try:
            rel = path.resolve().relative_to(self.root).as_posix()
        except (ValueError, OSError):
            self.issue(origin, "teilweise", "Dateiverweis ausserhalb /config oder nicht auflösbar")
            return []
        # Symlinks are intentionally never followed, even if pointing inside /config.
        if any(p.is_symlink() for p in [path, *list(path.parents)[:-1]]):
            self.issue(origin, "teilweise", "Dateiverweis über Symlink ausgelassen")
            return []
        if directory:
            found = sorted(p for p in self.contents if p.startswith(rel.rstrip("/") + "/") and Path(p).suffix in {".yaml", ".yml"})
            if not path.is_dir():
                self.issue(origin, "teilweise", "Verzeichnisverweis fehlt: " + rel)
            return found
        if rel not in self.contents:
            self.issue(origin, "teilweise", "Dateiverweis fehlt oder wurde ausgelassen: " + rel)
            return []
        return [rel]

    def find_dependencies(self):
        for origin, root in self.nodes.items():
            visited = set()
            def walk(node):
                if node is None or id(node) in visited:
                    return
                visited.add(id(node))
                if isinstance(node, yaml.ScalarNode) and node.tag.startswith("!include"):
                    targets = self.resolve_ref(origin, node.value, node.tag.startswith("!include_dir_"))
                    self.dependencies.append({"quelle": origin, "tag": node.tag, "verweis": self.redactor.text(node.value), "ziele": targets})
                elif isinstance(node, yaml.MappingNode):
                    for key, value in node.value:
                        walk(value)
                elif isinstance(node, yaml.SequenceNode):
                    for value in node.value:
                        walk(value)
            walk(root)
        for item in self.snapshot.get("local_references", []):
            targets = self.resolve_ref("configuration.yaml", item)
            self.dependencies.append({"quelle": "Laufzeit/Dashboard", "tag": "lokale Ressource/Datei", "verweis": item, "ziele": targets})
            self.refs.update(targets)
        changed = True
        while changed:
            changed = False
            for dep in self.dependencies:
                if dep["quelle"] in self.refs:
                    for target in dep["ziele"]:
                        if target not in self.refs:
                            self.refs.add(target)
                            changed = True
        for dep in self.dependencies:
            dep["quelle_referenziert"] = dep["quelle"] in self.refs or dep["quelle"] == "Laufzeit/Dashboard"
        if "configuration.yaml" not in self.contents:
            self.issue("configuration.yaml", "fehlend", "Hauptkonfiguration nicht enthalten")

    def write_sources(self):
        processed = 0
        total = len(self.contents)
        for row in self.inventory:
            self.check()
            rel = row["pfad"]
            if rel not in self.contents:
                continue
            self.report("Quelldateien maskieren", 38 + 30 * processed / max(1, total), processed, total, "Dateien")
            processed += 1
            source, ext, is_log = self.contents[rel]
            before = self.redactor.count
            try:
                text = self.redactor.source(source, ext, rel)
            except (ValueError, yaml.YAMLError):
                row.update(entscheidung="ausgelassen", grund="Maskierung nicht sicher möglich")
                self.issue(rel, "teilweise", row["grund"])
                continue
            prefix = "diagnose/logs/" if is_log else "erweiterungen/" if rel.startswith(("custom_components/", "www/", "python_scripts/", "custom_templates/", "pyscript/")) else "konfiguration/"
            name = prefix + rel
            if self.add(name, text.encode()):
                row.update(entscheidung="enthalten", archivpfad=self.archive_name(name), grund="",
                           zuordnung="nachgewiesene Einbindung" if rel in self.refs else "ergänzender Dateibestand; Aktivität nicht hieraus ableiten",
                           maskierungen=self.redactor.count - before)
            else:
                row.update(entscheidung="ausgelassen", grund="Archivlimit erreicht")
        self.report("Quelldateien maskieren", 68, processed, total, "Dateien")

    def build(self):
        self.check()
        self.private.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.private.is_symlink():
            raise ValueError("Exportverzeichnis darf kein Symlink sein")
        os.chmod(self.private, 0o700)
        self.report("Dateien erfassen", 30, 0, unit="Dateien geprüft")
        self.read_secrets()
        self.redactor.learn(self.snapshot)
        self.inventory_files()
        if not any(is_log for _, _, is_log in self.contents.values()):
            detail = "Keine unterstützte lokale HA-Logdatei vorhanden; vollständige Core-/Supervisor-Logs sind nicht enthalten"
            if "diagnose/system_log.json" in self.snapshot.get("files", {}):
                detail += "; der begrenzte HA-Fehlerspeicher ist separat enthalten"
            self.issue("HA-Logs", "nicht_erfasst", detail)
        self.report("Einbindungen prüfen", 35)
        self.find_dependencies()
        runtime_files = {}
        for name, value in self.snapshot.get("files", {}).items():
            if ".." in Path(name).parts or Path(name).is_absolute() or name in GENERATED_PATHS:
                self.issue("Laufzeit", "teilweise", "Ungültiger oder reservierter Archivpfad verworfen")
                continue
            runtime_files[name] = value
            self.archive_name(name)
        self.report("Quelldateien maskieren", 38, 0, len(self.contents), "Dateien")
        self.write_sources()
        self.report("HA-Laufzeitdaten maskieren", 68, 0, len(runtime_files), "Datensätze")
        for index, (name, value) in enumerate(runtime_files.items()):
            self.add(name, dump_json(self.redactor.object(self.archive_references(value), name)))
            self.report("HA-Laufzeitdaten maskieren", 68 + 5 * (index + 1) / max(1, len(runtime_files)), index + 1, len(runtime_files), "Datensätze")
        referenced_secrets = [{"name": name, "vorhanden": name in self.secret_present} for name in sorted(self.redactor.secret_names)]
        if any(not row["vorhanden"] for row in referenced_secrets):
            self.issue("secrets", "teilweise", "Mindestens ein verwendeter Secret-Name fehlt")
        self.add("inventar/secrets_nur_namen.json", dump_json(referenced_secrets))
        self.add("inventar/abhaengigkeiten.json", dump_json(self.redactor.object(self.dependencies)))
        self.add("inventar/dateien.json", dump_json(self.redactor.object(self.inventory)))
        listing = ["Pfad\tTyp\tBytes\tEntscheidung\tGrund\tArchivpfad"]
        for row in self.inventory:
            listing.append("\t".join(str(row.get(k, "—")).replace("\n", " ").replace("\t", " ") for k in ["pfad", "typ", "bytes", "entscheidung", "grund", "archivpfad"]))
        self.add("inventar/dateiliste.txt", self.redactor.text("\n".join(listing) + "\n").encode())
        context_path = self.root / "ha_pruefexport_kontext.md"
        context = "# Projektkontext\n\nStandort, Hardware und HA-Zeitzone aus den exportierten Konfigurations- und Laufzeitdaten ableiten.\nKeine persönlichen Vorgaben oder Geräte erfinden. Zusätzlich gepflegten Kontext unten beachten.\nFehlende/veraltete Werte nie pauschal als 0 oder gesund anzeigen. Tatsächliche Entitäten verwenden.\nDeutsch mit ss; Originalnamen beibehalten.\n"
        if context_path.as_posix().startswith(self.root.as_posix()) and "ha_pruefexport_kontext.md" in self.contents:
            context += "\n## Zusätzlich gepflegter Kontext\n\n" + self.redactor.text(self.contents["ha_pruefexport_kontext.md"][0])
        self.add("KONTEXT.md", context.encode())
        task = """# Prüfauftrag: gesamte Home-Assistant-Prüfung

Prüfe dieses Archiv systematisch anhand des aktuellen exportierten Stands.
Hauptziel: Jede Dashboardkachel soll korrekt anzeigen, sinnvoll bedienbar sein und
auch bei fehlenden oder veralteten Daten zuverlässig reagieren.
Der Auftrag ist modellagnostisch. Beachte KONTEXT.md und den tatsächlich erfassten Umfang.

## 1. Exportgrundlage und Exporter prüfen

Beginne mit EXPORTBERICHT.md, manifest.json, inventar/dateiliste.txt,
inventar/dateien.json und inventar/abhaengigkeiten.json.
Vergleiche Archivinhalt, SHA256/Grössen, Dateiliste, Einbindungen, Live-Dashboards,
Laufzeitdaten und registrierte Integrationen. Suche nach ausgelassenen prüfrelevanten
Daten, unbekannten Speicherformaten, Maskierungsfehlern und falschen
Vollständigkeitsbehauptungen. Beachte nicht inventarisierte Unterbäume, Limits und
Grenzen externer Apps. Unbekannte Quellen bleiben ungeklärt; fehlende Inhalte nicht erfinden.
Prüfe den enthaltenen Quellcode unter erweiterungen/custom_components/ha_pruefexport/,
soweit vorhanden, auf Fehler und Verbesserungsbedarf. Benenne nötige Anpassungen an
Erfassung, Maskierung, Kompatibilität oder Bedienung und begründe sie mit dem Archivstand.
Bei fehlenden relevanten Quellen liefere die mögliche Teilprüfung trotzdem und
benenne genau, was für eine weitergehende Prüfung nachgeliefert werden muss.

## 2. Home Assistant und jede Dashboardkachel prüfen

Erstelle eine Ansicht-/Karten-/Abhängigkeitsübersicht und einen Prüfplan.
Gehe alle exportierten Ansichten und Kacheln durch; eine allgemeine Checkliste genügt nicht.
Prüfe Konfiguration, Templates, Automationen, Skripte und Erweiterungen auf Fehler,
Datenlücken, Einheiten, Zeitstempel, konfigurierte HA-Zeitzone/DST, Forecastbezug,
Verfügbarkeit, Navigation und Aktionsparameter. Bereits bearbeitete Karten auf ihrem
aktuellen Stand prüfen. Verwende ausschliesslich nachgewiesene Entitäten und Attribute.
Unterscheide echte Nullwerte von fehlenden Daten und Quellenfrische von HA
last_reported/last_changed. Simuliere sinnvolle Fehlerfälle lokal.
Nutze offizielle Quellen passend zu den exportierten Versionen.

## 3. Konkrete Ergebnisse und Änderungen liefern

Priorisiere nachgewiesene Fehler und sinnvolle Verbesserungen. Trenne belegte Befunde
von Annahmen und dokumentiere die verbleibenden Exportlücken.
Liefere bei notwendigen Kartenänderungen komplette herunterladbare Ersatz-YAML je
Kartenblock mit Ersetzungsanweisung. Konfiguration und Automationen nur bei
nachgewiesenem Bedarf ändern. Für nötige Exporter-Anpassungen liefere konkrete
Codeänderungen mit passenden Prüfungen und Update-Anweisungen.
Beschreibe durchgeführte Prüfungen und die noch nötigen Prüfungen auf dem laufenden HA.
Behaupte keinen Live-Test ohne tatsächlichen Zugriff; keine Geräteaktionen oder SMS.
"""
        self.add("PRUEFAUFTRAG.md", task.encode())
        self.report("Abschliessende Maskierung", 73, 0, len(self.payload), "Dateien")
        # Sources can teach additional literals during rendering. Apply the completed
        # literal set to earlier output and generated metadata before hashing any bytes.
        for index, (name, data) in enumerate(list(self.payload.items())):
            self.check()
            self.payload[name] = self.redactor.text(data.decode("utf-8")).encode("utf-8")
            self.report("Abschliessende Maskierung", 73 + 8 * (index + 1) / max(1, len(self.payload)), index + 1, len(self.payload), "Dateien")
        if self.redactor.redacted_keys:
            self.issue("Maskierte Feldnamen", "teilweise",
                       "Mindestens ein Feldname enthält einen bekannten Zugangsdatenwert und wurde maskiert; Strukturzuordnung eingeschränkt")
        if self.renamed_paths:
            self.issue("Maskierte Dateinamen", "teilweise",
                       "Mindestens ein Archivpfad wurde maskiert; Inventar und Manifest verweisen auf die tatsächlich enthaltenen Namen")
        self.report("Manifest und Exportbericht erstellen", 81)
        # Metadata must remain possible even when source payload hits its budget.
        status = "teilweise" if self.issues else "vollstaendig"
        finished = utcnow()
        report = ["# Exportbericht", "", "Status: **" + status + "**", "",
                  "Beginn: " + self.snapshot.get("started", "unbekannt"), "Ende: " + finished,
                  "Prüfauftrag: " + self.mode, "", "Vollständigkeit bezieht sich auf den beschriebenen Exportumfang, nicht auf die Gesundheit von HA.",
                  "Die Lesevorgänge bilden keinen atomaren Gesamtzustand. Zustands-/Quellenzeitstempel bleiben verschieden.",
                  "Maskierte Werte sind als " + self.redactor.marker + " gekennzeichnet. Unbekannte individuell benannte Geheimnisse können unerkannt bleiben.",
                  "Keine Kopie von Auth-Dateien, Secrets-Inhalten, Recorder-Datenbank, Medien oder Backups.",
                  "Ausgeschlossene Verzeichnis-Unterbäume sind im Inventar markiert; deren Inhalt wurde nicht einzeln aufgelistet.",
                  "Externe Apps/Controller-Konfigurationen ausserhalb /config werden nicht eingesammelt.",
                  "", "## Einschränkungen"]
        report.extend("- " + item["bereich"] + " · " + item["status"] + ": " + item["grund"] for item in self.issues)
        if not self.issues:
            report.append("Keine erkannten Erfassungslücken im vorgesehenen Umfang; keine Garantie für unbekannte externe Abhängigkeiten.")
        report += ["", "Maskierungen: " + str(self.redactor.count), "", "Manifest-Prüfsummen beziehen sich auf die tatsächlich exportierten, bereinigten Bytes.", "Das Manifest enthält keine Prüfsumme seiner eigenen Datei."]
        self.payload["EXPORTBERICHT.md"] = self.redactor.text("\n".join(report) + "\n").encode()
        manifest = {"format_version": FORMAT_VERSION, "exporter_version": VERSION, "status": status, "pruefmodus": self.mode,
                    "started_utc": self.redactor.object(self.snapshot.get("started")), "finished_utc": finished,
                    "zeitbasis_archivname": "UTC", "limits": {"file_bytes": self.max_file, "payload_bytes": self.max_total, "inventory_files": self.max_entries},
                    "issues": self.redactor.object(self.issues), "maskierungen": self.redactor.count,
                    "files": [{"path": name, "bytes": len(data), "sha256": digest(data)} for name, data in sorted(self.payload.items())]}
        self.payload["manifest.json"] = dump_json(manifest)
        # Independent final scan. All source bytes, source-derived archive names
        # and variable manifest data are checked. Fixed public schema labels and
        # computed hashes/numbers are not credential values, even when a generic
        # source field named "key" happens to contain the same public label.
        self.report("Maskierungskontrolle", 83, 0, len(self.payload), "Dateien")
        for index, (name, data) in enumerate(self.payload.items()):
            self.check()
            if name not in GENERATED_PATHS and self.redactor.contains_known(name):
                raise MaskingCheckError("Dateiname", name)
            if name != "manifest.json" and self.redactor.contains_known(data.decode("utf-8")):
                raise MaskingCheckError("Archivinhalt", name)
            self.report("Maskierungskontrolle", 83 + 6 * (index + 1) / max(1, len(self.payload)), index + 1, len(self.payload), "Dateien")
        parsed_manifest = json.loads(self.payload["manifest.json"])
        variable_metadata = {"start": parsed_manifest["started_utc"],
                             "issues": parsed_manifest["issues"],
                             "paths": [row["path"] for row in parsed_manifest["files"]
                                       if row["path"] not in GENERATED_PATHS]}
        if self.redactor.contains_known(dump_json(variable_metadata).decode("utf-8")):
            raise MaskingCheckError("Manifestdaten", "manifest.json")
        expected_files = set(self.payload) - {"manifest.json"}
        rows = parsed_manifest["files"]
        if len(rows) != len(expected_files) or {row["path"] for row in rows} != expected_files:
            raise ValueError("Manifest-Dateiliste stimmt nicht mit Archivinhalt überein")
        for row in rows:
            data = self.payload[row["path"]]
            if row["bytes"] != len(data) or row["sha256"] != digest(data):
                raise ValueError("Manifest-Prüfsumme stimmt nicht mit Archivinhalt überein")
        import uuid
        filename = "ha_pruefexport_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8] + ".zip"
        temporary = self.private / (filename + ".tmp")
        target = self.private / filename
        try:
            self.report("ZIP schreiben", 89, 0, len(self.payload), "Dateien")
            with temporary.open("xb") as handle:
                os.chmod(temporary, 0o600)
                with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                    for index, (name, data) in enumerate(sorted(self.payload.items())):
                        self.check()
                        archive.writestr(name, data)
                        self.report("ZIP schreiben", 89 + 7 * (index + 1) / max(1, len(self.payload)), index + 1, len(self.payload), "Dateien")
            with zipfile.ZipFile(temporary) as archive:
                self.report("ZIP prüfen", 96, 0, len(self.payload), "Dateien")
                for index, entry in enumerate(archive.infolist()):
                    # Reading each member to EOF verifies its CRC. Chunking also
                    # allows cancellation during the verification of large files.
                    with archive.open(entry) as member:
                        while member.read(1024 * 1024):
                            self.check()
                    self.check()
                    self.report("ZIP prüfen", 96 + 2 * (index + 1) / max(1, len(self.payload)), index + 1, len(self.payload), "Dateien")
            self.check()
            self.report("ZIP freigeben", 98)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return {"filename": filename, "bytes": target.stat().st_size, "finished": finished,
                "status": status, "files": len(self.payload), "sources": sum(r.get("entscheidung") == "enthalten" for r in self.inventory),
                "issues": len(self.issues), "maskierungen": self.redactor.count, "mode": self.mode}


def create_export(root, private, snapshot, mode="gesamt", cancel=None, progress=None):
    builder = Builder(root, private, snapshot, mode, cancel, progress=progress)
    try:
        return builder.build()
    except ExportCancelled:
        raise
    except Exception as error:
        raise ExportFailure(failure_details(error, builder.phase)) from None
