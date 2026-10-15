"""Offline tests: real ZIPs with synthetic HA data; no connection to the user's HA."""
import asyncio
import importlib.util
import json
import pathlib
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "ha_pruefexport"
pkg = types.ModuleType("ha_pruefexport")
pkg.__path__ = [str(PACKAGE)]
sys.modules["ha_pruefexport"] = pkg
from ha_pruefexport.exporter import Builder, Redactor, ExportCancelled, ExportFailure, create_export, digest, dump_json


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.write("configuration.yaml", "homeassistant:\n  time_zone: UTC\nautomation: !include automations.yaml\n")
        self.write("automations.yaml", "[]\n")
        self.write("home-assistant.log", "")
        self.snapshot = {"started": "2026-01-15T06:00:00+00:00", "issues": [], "files": {
            "runtime/zustaende.json": [{"entity_id": "sensor.real", "state": "0", "attributes": {"valid": False, "missing": None, "zero": 0}}]}, "local_references": []}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, value):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value)

    def build(self, **kwargs):
        builder = Builder(self.root, self.root / ".ha_pruefexport", self.snapshot, "methode", **kwargs)
        result = builder.build()
        with zipfile.ZipFile(builder.private / result["filename"]) as archive:
            self.assertIsNone(archive.testzip())
            files = {name: archive.read(name) for name in archive.namelist()}
        return builder, result, files

    def test_manifest_inventory_and_types(self):
        before = (self.root / "configuration.yaml").read_bytes()
        builder, result, files = self.build()
        self.assertEqual(result["status"], "vollstaendig")
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(set(files) - {"manifest.json"}, {r["path"] for r in manifest["files"]})
        for row in manifest["files"]:
            self.assertEqual(row["bytes"], len(files[row["path"]]))
            self.assertEqual(row["sha256"], digest(files[row["path"]]))
        for row in json.loads(files["inventar/dateien.json"]):
            if row["entscheidung"] == "enthalten":
                self.assertIn(row["archivpfad"], files)
        attributes = json.loads(files["runtime/zustaende.json"])[0]["attributes"]
        self.assertIs(attributes["valid"], False)
        self.assertIsNone(attributes["missing"])
        self.assertEqual(attributes["zero"], 0)
        self.assertEqual(before, (self.root / "configuration.yaml").read_bytes())
        self.assertEqual(manifest["pruefmodus"], "gesamt")
        self.assertIn("alle exportierten Ansichten und Kacheln".encode(), files["PRUEFAUFTRAG.md"])

    def test_default_and_legacy_export_have_same_combined_instruction(self):
        _, legacy, legacy_files = self.build()
        current = create_export(self.root, self.root / ".ha_pruefexport", self.snapshot)
        with zipfile.ZipFile(self.root / ".ha_pruefexport" / current["filename"]) as archive:
            task = archive.read("PRUEFAUFTRAG.md")
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(task, legacy_files["PRUEFAUFTRAG.md"])
        self.assertEqual((legacy["mode"], current["mode"], manifest["pruefmodus"]), ("gesamt", "gesamt", "gesamt"))
        for requirement in ("inventar/dateiliste.txt", "inventar/abhaengigkeiten.json",
                            "Exporter prüfen", "jede Dashboardkachel prüfen",
                            "erweiterungen/custom_components/ha_pruefexport/", "Maskierungsfehlern",
                            "unbekannten Speicherformaten", "Codeänderungen", "KONTEXT.md"):
            self.assertIn(requirement, task.decode())
        self.assertNotIn("Keine fachliche Prüfung", task.decode())

    def test_secrets_inline_and_global_redaction(self):
        self.write("secrets.yaml", "api: my_very_secret_123\n")
        self.write("configuration.yaml", 'password: short\npin: 1234\napi_key: !secret api\ntemplate: "{{ states(\'sensor.real\') }}"\n')
        self.write("local.py", 'token = "another_secret_123"\nurl = "https://u:abc@host/x?api_key=abcdef"\n')
        self.snapshot["files"]["runtime/something.json"] = {"token": "another_secret_123", "data": {"template": "{{ states('sensor.real') }}", "reference": "my_very_secret_123"}, "options": {"maximum": 100}}
        _, _, files = self.build()
        combined = b"\n".join(files.values()).decode()
        for secret in ("my_very_secret_123", "another_secret_123", "short", "1234", "u:abc@", "api_key=abcdef"):
            self.assertNotIn(secret, combined)
        self.assertNotIn("konfiguration/secrets.yaml", files)
        self.assertIn("!secret api", files["konfiguration/configuration.yaml"].decode())
        self.assertIn("states('sensor.real')", files["konfiguration/configuration.yaml"].decode())
        self.assertEqual(json.loads(files["inventar/secrets_nur_namen.json"]), [{"name": "api", "vorhanden": True}])
        self.assertEqual(json.loads(files["runtime/something.json"])["options"]["maximum"], 100)

    def test_custom_project_context_is_preserved_and_redacted(self):
        self.write("ha_pruefexport_kontext.md", "Kompakte Klimabedienung beibehalten.\nPrivater Wert: custom_context_secret_123\n")
        self.write("secrets.yaml", "api: custom_context_secret_123\n")
        _, _, files = self.build()
        context = files["KONTEXT.md"].decode()
        self.assertIn("Kompakte Klimabedienung beibehalten.", context)
        self.assertIn("[MASKIERT]", context)
        self.assertNotIn("custom_context_secret_123", context)

    def test_audit_uses_configured_timezone(self):
        self.snapshot["files"]["runtime/exportzeit.json"] = {"ha_timezone": "America/New_York"}
        builder = Builder(self.root, self.root / ".ha_pruefexport", self.snapshot, "gesamt")
        result = builder.build()
        with zipfile.ZipFile(builder.private / result["filename"]) as archive:
            context = archive.read("KONTEXT.md").decode()
            task = archive.read("PRUEFAUFTRAG.md").decode()
            runtime = json.loads(archive.read("runtime/exportzeit.json"))
        self.assertEqual(runtime["ha_timezone"], "America/New_York")
        self.assertIn("konfigurierte HA-Zeitzone/DST", task)
        for text in (context, task):
            self.assertNotIn("UTC", text)

    def test_secret_literal_in_json_field_name_no_longer_aborts(self):
        self.snapshot["files"]["runtime/key_metadata.json"] = {
            "integration": {"key": "entity_id"},
            "states": [{"entity_id": "sensor.demo", "state": "0"}],
        }
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertNotIn(b"entity_id", b"\n".join(files.values()))
        self.assertIn("Maskierte Feldnamen", files["EXPORTBERICHT.md"].decode())
        self.assertEqual(json.loads(files["runtime/key_metadata.json"])["states"][0]["state"], "0")
        manifest = json.loads(files["manifest.json"])
        for row in manifest["files"]:
            self.assertEqual(row["sha256"], digest(files[row["path"]]))
            self.assertEqual(row["bytes"], len(files[row["path"]]))

    def test_colliding_redacted_keys_preserve_both_values(self):
        redactor = Redactor()
        # Use non-credential field names: secret_* fields are now sensitive too.
        redactor.remember("long_literal_one")
        redactor.remember("long_literal_two")
        output = redactor.object({"long_literal_one": 1, "long_literal_two": 2})
        self.assertEqual(list(output.values()), [1, 2])
        self.assertEqual(len(output), 2)
        self.assertNotIn("long_literal", str(output))

    def test_final_masking_control_still_blocks_unredacted_output(self):
        self.write("secrets.yaml", "api: sensitive_literal_123\n")
        self.write("local.txt", "sensitive_literal_123\n")
        with patch.object(Redactor, "text", lambda self, value: value):
            with self.assertRaises(ExportFailure) as caught:
                create_export(self.root, self.root / ".ha_pruefexport", self.snapshot, "methode")
        self.assertEqual(caught.exception.details["phase"], "Maskierungskontrolle")
        self.assertEqual(caught.exception.details["fehlerart"], "MaskingCheckError")
        self.assertEqual(caught.exception.details["pruefbereich"], "Archivinhalt")
        self.assertRegex(caught.exception.details["datei_id"], r"^[0-9a-f]{12}$")
        self.assertRegex(caught.exception.details["stelle"], r"exporter\.py:\d+")
        self.assertNotIn("sensitive_literal_123", str(caught.exception.details))
        self.assertEqual(list((self.root / ".ha_pruefexport").glob("*.zip")), [])

    def test_public_manifest_label_is_not_a_source_credential(self):
        self.snapshot["files"]["runtime/key.json"] = {"key": "started_utc"}
        _, _, files = self.build()
        self.assertNotIn(b"started_utc", files["runtime/key.json"])
        self.assertIn("started_utc", json.loads(files["manifest.json"]))

    def test_known_value_in_filename_has_consistent_manifest_and_inventory(self):
        self.snapshot["files"]["runtime/key.json"] = {"key": "configuration.yaml"}
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertFalse(any("configuration.yaml" in name for name in files))
        self.assertNotIn(b"configuration.yaml", b"\n".join(files.values()))
        self.assertIn("Maskierte Dateinamen", files["EXPORTBERICHT.md"].decode())
        rows = json.loads(files["inventar/dateien.json"])
        for row in rows:
            if row.get("entscheidung") == "enthalten":
                self.assertIn(row["archivpfad"], files)
        for row in json.loads(files["manifest.json"])["files"]:
            self.assertEqual(row["sha256"], digest(files[row["path"]]))
            self.assertEqual(row["bytes"], len(files[row["path"]]))

    def test_colliding_filenames_keep_sources_and_dashboard_references(self):
        first, second = "credential_one_123", "credential_two_123"
        self.write(first + ".yaml", "value: 1\n")
        self.write(second + ".yaml", "value: 2\n")
        self.snapshot["files"].update({
            "dashboards/" + first + ".json": {"title": "A"},
            "dashboards/" + second + ".json": {"title": "B"},
            "inventar/dashboards.json": [
                {"archivpfad": "dashboards/" + first + ".json"},
                {"archivpfad": "dashboards/" + second + ".json"}],
            "runtime/credentials.json": {"access_token": first, "api_key": second}})
        _, _, files = self.build()
        dashboard_paths = [r["archivpfad"] for r in json.loads(files["inventar/dashboards.json"])]
        self.assertEqual(len(set(dashboard_paths)), 2)
        self.assertEqual({json.loads(files[p])["title"] for p in dashboard_paths}, {"A", "B"})
        source_paths = [r["archivpfad"] for r in json.loads(files["inventar/dateien.json"])
                        if r.get("entscheidung") == "enthalten" and "[MASKIERT]" in r["pfad"]]
        self.assertEqual(len(set(source_paths)), 2)
        self.assertEqual({files[p] for p in source_paths}, {b"value: 1\n", b"value: 2\n"})
        for secret in (first, second):
            self.assertFalse(any(secret in p for p in files))
            self.assertNotIn(secret.encode(), b"\n".join(files.values()))

    def test_redaction_marker_does_not_recreate_a_known_literal(self):
        for literal in ("MASKIERT", "[MASKIERT]"):
            with self.subTest(literal=literal):
                self.snapshot["files"]["runtime/marker.json"] = {
                    "token": literal, "reference": "prefix " + literal + " suffix"}
                _, _, files = self.build()
                self.assertNotIn(literal.encode(), b"\n".join(files.values()))
                self.assertIn(b"[MASK]", files["runtime/marker.json"])
                self.assertIn(b"[MASK]", files["EXPORTBERICHT.md"])

    def test_final_control_blocks_a_secret_in_archive_filename(self):
        secret = "sensitive_filename_123"
        self.snapshot["files"]["runtime/" + secret + ".json"] = {}
        self.snapshot["files"]["runtime/key.json"] = {"token": secret}
        with patch.object(Redactor, "text", lambda self, value: value):
            with self.assertRaises(ExportFailure) as caught:
                create_export(self.root, self.root / ".ha_pruefexport", self.snapshot, "methode")
        self.assertEqual(caught.exception.details["pruefbereich"], "Dateiname")
        self.assertNotIn(secret, str(caught.exception.details))
        self.assertEqual(list((self.root / ".ha_pruefexport").glob("*.zip")), [])

    def test_final_control_blocks_unmasked_variable_manifest_data(self):
        secret = "sensitive_manifest_123"
        self.write("secrets.yaml", "api: " + secret + "\n")
        self.snapshot["issues"] = [{"bereich": "test", "status": "teilweise", "grund": secret}]
        with patch.object(Redactor, "object", lambda self, value, path="": value):
            with self.assertRaises(ExportFailure) as caught:
                create_export(self.root, self.root / ".ha_pruefexport", self.snapshot, "methode")
        self.assertEqual(caught.exception.details["pruefbereich"], "Manifestdaten")
        self.assertNotIn(secret, str(caught.exception.details))
        self.assertEqual(list((self.root / ".ha_pruefexport").glob("*.zip")), [])

    def test_final_control_rejects_an_incorrect_manifest_hash(self):
        def corrupt_manifest(value):
            if isinstance(value, dict) and "format_version" in value:
                value["files"][0]["sha256"] = "0" * 64
            return dump_json(value)
        with patch("ha_pruefexport.exporter.dump_json", corrupt_manifest):
            with self.assertRaises(ExportFailure) as caught:
                create_export(self.root, self.root / ".ha_pruefexport", self.snapshot, "methode")
        self.assertEqual(caught.exception.details["phase"], "Maskierungskontrolle")
        self.assertEqual(caught.exception.details["fehlerart"], "ValueError")
        self.assertEqual(list((self.root / ".ha_pruefexport").glob("*.zip")), [])

    def test_runtime_cannot_replace_the_generated_manifest(self):
        self.snapshot["files"]["manifest.json"] = {"injected": True}
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertNotIn("injected", json.loads(files["manifest.json"]))
        self.assertIn("reservierter Archivpfad", files["EXPORTBERICHT.md"].decode())

    def test_ha_storage_keys_preserve_helper_domains_and_source_names(self):
        for key in ("core.config_entries", "core.entity_registry", "core.device_registry", "input_text", "input_number", "lovelace"):
            self.write(".storage/" + key, json.dumps({"version": 1, "minor_version": 1, "key": key, "data": {"items": []}}))
        self.snapshot["files"]["runtime/test.json"] = {"entity_id": "input_text.demo", "state": "sensitive_input_text_123"}
        _, result, files = self.build()
        self.assertEqual(result["status"], "vollstaendig")
        self.assertEqual(json.loads(files["runtime/test.json"])["entity_id"], "input_text.demo")
        self.assertNotIn(b"sensitive_input_text_123", b"\n".join(files.values()))
        for key in ("core.config_entries", "core.entity_registry", "core.device_registry", "input_text", "input_number", "lovelace"):
            name = "konfiguration/.storage/" + key
            self.assertIn(name, files)
            self.assertEqual(json.loads(files[name])["key"], key)

    def test_storage_exception_does_not_apply_to_nested_credentials(self):
        secret = "nested_sensitive_key_123"
        self.write(".storage/core.config_entries", json.dumps({"version": 1, "minor_version": 1,
            "key": "core.config_entries", "data": {"entries": [{"data": {"key": secret}, "reference": secret}]}}))
        _, _, files = self.build()
        self.assertEqual(json.loads(files["konfiguration/.storage/core.config_entries"])["key"], "core.config_entries")
        self.assertNotIn(secret.encode(), b"\n".join(files.values()))

    def test_storage_exception_requires_correct_path_and_format(self):
        value = {"version": 1, "minor_version": 1, "key": "core.entity_registry", "data": {}}
        for path, data in (("local.json", value), (".storage/core.config_entries", value),
                           (".storage/core.entity_registry", {**value, "version": "1"}),
                           (".storage/core.entity_registry", {**value, "data": "not a storage collection"})):
            with self.subTest(path=path, data_type=type(data["data"]).__name__):
                redactor = Redactor()
                output = json.loads(redactor.source(json.dumps(data), ".json", path))
                self.assertEqual(output["key"], "[MASKIERT]")
                self.assertIn("core.entity_registry", redactor.known)

    def test_real_credential_matching_a_storage_label_remains_masked(self):
        literal = "input_text"
        self.write("secrets.yaml", "actual_secret: " + literal + "\n")
        self.write(".storage/input_text", json.dumps({"version": 1, "minor_version": 1, "key": literal, "data": {}}))
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertFalse(any(literal in p for p in files))
        self.assertNotIn(literal.encode(), b"\n".join(files.values()))

    def test_old_dated_audit_export_is_skipped_without_deleting_files(self):
        old = "ha_pruefung_20260101_000000"
        self.write(old + "/configuration.yaml", "password: old_sensitive_password_123\n")
        self.write(old + "/nested/file.txt", "obsolete copy\n")
        self.write("ha_pruefung_normal/file.txt", "actual project source\n")
        _, _, files = self.build()
        self.assertFalse(any(old in p for p in files))
        self.assertNotIn(b"old_sensitive_password_123", b"\n".join(files.values()))
        self.assertIn("konfiguration/ha_pruefung_normal/file.txt", files)
        rows = json.loads(files["inventar/dateien.json"])
        row = next(r for r in rows if r["pfad"] == old + "/")
        self.assertEqual(row["entscheidung"], "ausgelassen")
        self.assertIn("Früheres Prüfexport", row["grund"])
        self.assertTrue((self.root / old / "configuration.yaml").is_file())
        self.assertNotIn("nested/file.txt", str(rows))

    def test_absent_local_logs_are_an_explicit_scope_note(self):
        (self.root / "home-assistant.log").unlink()
        _, result, files = self.build()
        self.assertEqual(result["status"], "vollstaendig")
        self.assertEqual(result["issues"], 0)
        self.assertEqual(result["notes"], 1)
        self.assertIn("HA-Logs", files["EXPORTBERICHT.md"].decode())
        self.assertIn("vollständige Core-/Supervisor-Logs", files["EXPORTBERICHT.md"].decode())

    def test_global_yaml_redaction_keeps_plain_scalars_as_strings(self):
        secret = "sensitive_entity_123"
        self.write("secrets.yaml", "api: " + secret + "\n")
        self.write("plain.yaml", "action: " + secret + ".turn_off\nreference: " + secret + "\n" + secret + ": value\n")
        _, _, files = self.build()
        import yaml
        value = yaml.safe_load(files["konfiguration/plain.yaml"])
        self.assertEqual(value["action"], "[MASKIERT].turn_off")
        self.assertEqual(value["reference"], "[MASKIERT]")
        self.assertEqual(value["[MASKIERT]"], "value")
        self.assertNotIn(secret.encode(), b"\n".join(files.values()))

    def test_yaml_masking_preserves_include_and_secret_tags(self):
        secret = "sensitive_reference_123"
        self.write("secrets.yaml", "api: " + secret + "\n")
        self.write("tagged.yaml", "source: !include " + secret + ".yaml\npassword: !secret " + secret + "\ninput_text:\n  demo:\n    initial: !secret " + secret + "\n")
        _, _, files = self.build()
        import yaml
        node = yaml.compose(files["konfiguration/tagged.yaml"])
        values = {k.value: v for k,v in node.value}
        self.assertEqual(values["source"].tag, "!include")
        self.assertEqual(values["source"].value, "[MASKIERT].yaml")
        self.assertEqual(values["password"].tag, "!secret")
        self.assertEqual(values["password"].value, "[MASKIERT]")
        initial = values["input_text"].value[0][1].value[0][1]
        self.assertEqual(initial.tag, "!secret")
        self.assertEqual(initial.value, "[MASKIERT]")

    def test_unsafe_redaction_of_yaml_anchor_is_omitted_with_gap(self):
        secret = "sensitive_anchor_123"
        self.write("secrets.yaml", "api: " + secret + "\n")
        self.write("anchor.yaml", "value: &" + secret + " public\ncopy: *" + secret + "\n")
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertNotIn("konfiguration/anchor.yaml", files)
        rows = json.loads(files["inventar/dateien.json"])
        row = next(r for r in rows if r["pfad"] == "anchor.yaml")
        self.assertEqual(row["entscheidung"], "ausgelassen")
        self.assertTrue(row["grund"])

    def test_includes_future_dirs_and_cycle(self):
        self.write("configuration.yaml", "sensor: !include new/place.yaml\ntemplate: !include_dir_merge_list future\n")
        self.write("new/place.yaml", "x: !include ../configuration.yaml\n")
        self.write("future/new.yaml", "- a: 0\n")
        _, result, files = self.build()
        self.assertEqual(result["status"], "vollstaendig")
        inventory = json.loads(files["inventar/dateien.json"])
        self.assertTrue(all(r.get("zuordnung") == "nachgewiesene Einbindung" for r in inventory if r["pfad"] in {"new/place.yaml", "future/new.yaml"}))

    def test_missing_include_and_secret(self):
        self.write("configuration.yaml", "x: !include missing.yaml\npassword: !secret missing\n")
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertIn("missing.yaml", files["EXPORTBERICHT.md"].decode())
        self.assertEqual(json.loads(files["inventar/secrets_nur_namen.json"])[0]["vorhanden"], False)

    def test_storage_unknown_auth_never_exported(self):
        self.write(".storage/auth", '{"long_secret": "do_not_copy_this"}')
        self.write(".storage/new_kind", '{"new": true}')
        self.write(".storage/input_number", '{"data": {"items": [{"min": 0, "max": 10}]}}')
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertIn("konfiguration/.storage/input_number", files)
        self.assertNotIn(b"do_not_copy_this", b"\n".join(files.values()))
        self.assertNotIn("konfiguration/.storage/new_kind", files)

    def test_symlink_outside_and_binary_excluded(self):
        (self.root / "alias.yaml").symlink_to(self.root / "automations.yaml")
        self.write("configuration.yaml", "x: !include alias.yaml\ny: !include /outside/file.yaml\n")
        (self.root / "camera.jpg").write_bytes(b"private media")
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertNotIn("konfiguration/alias.yaml", files)
        self.assertNotIn(b"private media", b"\n".join(files.values()))

    def test_invalid_json_and_yaml_fail_closed(self):
        self.write("bad.json", '{"password": "PRIVATE_BAD_VALUE",')
        self.write("bad.yaml", 'x: [\npassword: PRIVATE_BAD_VALUE\n')
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertNotIn(b"PRIVATE_BAD_VALUE", b"\n".join(files.values()))

    def test_cancellation_does_not_publish(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(ExportCancelled):
            self.build(cancel=event)
        self.assertEqual(list((self.root / ".ha_pruefexport").glob("*.zip")), [])

    def test_limits_reported(self):
        self.write("large.txt", "A" * 20000)
        _, result, files = self.build(limits=(15000, 40000, 1000))
        self.assertEqual(result["status"], "teilweise")
        self.assertNotIn("konfiguration/large.txt", files)
        self.assertIn("Dateilimit", files["EXPORTBERICHT.md"].decode())

    def test_unknown_scalar_and_nonfinite_never_zero(self):
        r = Redactor()
        out = r.object({"nan": float("nan"), "obj": object(), "zero": 0, "empty": None, "false": False})
        self.assertIsInstance(out["nan"], dict)
        self.assertIsInstance(out["obj"], dict)
        self.assertEqual(out["zero"], 0)
        self.assertIsNone(out["empty"])
        self.assertIs(out["false"], False)
        self.assertNotIn("u:pw@", r.text("mysql://u:pw@host/db rtsp://u:pw@camera/stream"))

    def test_input_text_restore_and_initial_are_masked(self):
        self.write(".storage/core.restore_state", '{"data": [{"state": {"entity_id": "input_text.pin", "state": "7788"}}]}')
        self.write(".storage/input_text", '{"data": {"items": [{"id": "pin", "initial": "7788"}]}}')
        self.write("configuration.yaml", 'input_text:\n  pin:\n    initial: "7788"\ninput_number:\n  amount:\n    initial: 23\n')
        _, _, files = self.build()
        # A computed SHA256 or timestamp may coincidentally contain four digits.
        for name in ("konfiguration/.storage/core.restore_state", "konfiguration/.storage/input_text",
                     "konfiguration/configuration.yaml"):
            self.assertNotIn(b"7788", files[name])
        self.assertIn(b"initial: 23", files["konfiguration/configuration.yaml"])

    def test_unquoted_shell_secrets_and_camelcase(self):
        self.write("local.sh", "export API_KEY=VERY_PRIVATE_KEY_123\nPASSWORD=abc\n")
        self.snapshot["files"]["runtime/test.json"] = {"accessToken": "VERY_PRIVATE_KEY_123", "privateKey": "hidden_key_1234", "number": 0}
        _, _, files = self.build()
        combined = b"\n".join(files.values())
        for value in (b"VERY_PRIVATE_KEY_123", b"PASSWORD=abc", b"hidden_key_1234"):
            self.assertNotIn(value, combined)

    def test_gzip_equivalence_and_difference(self):
        import gzip
        self.write("www/card.js", "console.log('public');\n")
        (self.root / "www/card.js.gz").write_bytes(gzip.compress(b"console.log('public');\n"))
        _, result, files = self.build()
        self.assertEqual(result["status"], "vollstaendig")
        self.assertNotIn("erweiterungen/www/card.js.gz", files)
        (self.root / "www/card.js.gz").write_bytes(gzip.compress(b"different"))
        _, result, files = self.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertIn("weicht ab", files["EXPORTBERICHT.md"].decode())

    def test_late_cancellation_removes_temporary(self):
        event = threading.Event()
        original = zipfile.ZipFile.writestr
        def write_then_cancel(archive, *args, **kwargs):
            original(archive, *args, **kwargs)
            event.set()
        with patch.object(zipfile.ZipFile, "writestr", write_then_cancel):
            with self.assertRaises(ExportCancelled):
                self.build(cancel=event)
        self.assertEqual(list((self.root / ".ha_pruefexport").iterdir()), [])


# Minimal HA API doubles, deliberately not a live HA test.
ha = types.ModuleType("homeassistant")
ha.__path__ = []
core = types.ModuleType("homeassistant.core")
core.callback = lambda f: f
exceptions = types.ModuleType("homeassistant.exceptions")
exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
sys.modules.update({"homeassistant": ha, "homeassistant.core": core, "homeassistant.exceptions": exceptions})
from ha_pruefexport.manager import ExportManager


class FakeHass:
    def __init__(self, root):
        self.config = types.SimpleNamespace(path=lambda *parts: str(pathlib.Path(root).joinpath(*parts)))

    async def async_add_executor_job(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    def async_create_background_task(self, target, name):
        return asyncio.create_task(target, name=name)


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "configuration.yaml").write_text("default_config:\n")
        self.manager = ExportManager(FakeHass(self.root))
        await self.manager.async_load()

    async def asyncTearDown(self):
        await self.manager.async_stop()
        self.tmp.cleanup()

    async def test_initial_values_missing(self):
        attrs = self.manager.attributes()
        self.assertFalse(attrs["has_archive"])
        self.assertIsNone(attrs["archive_bytes"])
        self.assertIsNone(attrs["archive_finished"])

    async def test_safe_diagnostic_identifies_collection_phase_and_hides_message(self):
        async def fail(hass, progress=None):
            raise ValueError("https://provider.invalid/?token=do_not_log_this_123")
        with patch("ha_pruefexport.manager.collect", fail), self.assertLogs("ha_pruefexport.manager", level="ERROR") as logs:
            self.manager.start("methode")
            await self.manager.task
        attributes = self.manager.attributes()
        self.assertEqual(attributes["last_error_details"]["phase"], "HA-Daten sammeln")
        self.assertEqual(attributes["last_error_details"]["fehlerart"], "ValueError")
        self.assertRegex(attributes["last_error_details"]["stelle"], r"manager\.py:\d+")
        self.assertIn("HA-Daten sammeln", attributes["last_error"])
        self.assertNotIn("do_not_log_this", str(attributes) + str(logs.output))
        self.assertNotIn("provider.invalid", str(attributes) + str(logs.output))

    async def test_double_start_status_restart_failure_previous(self):
        async def collect(hass, progress=None):
            await asyncio.sleep(0.01)
            return {"started": "2026-01-15T06:00:00+00:00", "files": {}, "issues": [], "local_references": []}
        with patch("ha_pruefexport.manager.collect", collect):
            self.manager.start("methode")
            first_task = self.manager.task
            self.assertFalse(self.manager.start("methode"))
            self.assertIs(self.manager.task, first_task)
            await self.manager.task
        attrs = self.manager.attributes()
        self.assertTrue(attrs["has_archive"])
        self.assertEqual(attrs["pruefmodus"], "gesamt")
        first = attrs["archive_name"]
        other = ExportManager(self.manager.hass)
        await other.async_load()
        self.assertEqual(other.attributes()["archive_name"], first)
        async def fail(hass, progress=None):
            raise RuntimeError("a sensitive provider message")
        with patch("ha_pruefexport.manager.collect", fail):
            self.manager.start("methode")
            await self.manager.task
        self.assertEqual(self.manager.status["state"], "fehler")
        self.assertEqual(self.manager.attributes()["archive_name"], first)
        self.assertNotIn("sensitive", self.manager.status["last_error"])

    async def test_download_name_and_symlink(self):
        valid = "ha_pruefexport_20260115_060000_abcdef12.zip"
        (self.manager.private / valid).write_bytes(b"zip")
        self.assertIsNotNone(self.manager.archive_path(valid))
        for name in ("../configuration.yaml", "/etc/passwd", "whatever.zip", None):
            self.assertIsNone(self.manager.archive_path(name))
        (self.manager.private / valid).unlink()
        (self.manager.private / valid).symlink_to(self.root / "configuration.yaml")
        self.assertIsNone(self.manager.archive_path(valid))

    async def test_retention_three(self):
        for i in range(5):
            name = f"ha_pruefexport_20260115_06000{i}_abcdef12.zip"
            (self.manager.private / name).write_bytes(b"zip")
        self.manager.prune()
        self.assertEqual(len(list(self.manager.private.glob("*.zip"))), 3)

    async def test_interrupted_restore(self):
        self.manager.status["state"] = "laeuft"
        await self.manager.save()
        other = ExportManager(self.manager.hass)
        await other.async_load()
        self.assertEqual(other.status["state"], "fehler")


if __name__ == "__main__":
    unittest.main(verbosity=2)
