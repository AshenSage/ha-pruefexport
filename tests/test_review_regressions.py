"""Regressions from an archive review, with exclusively synthetic fixture data."""
import asyncio
import json
import types
import unittest

import test_collector_view
import test_export
from ha_pruefexport.collect import collect, history_snapshot


class SourceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_export.ExportTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_connectlife_public_commands_preserve_translations_and_unknown_keys_are_masked(self):
        path = "custom_components/connectlife/data_dictionaries/009-999.yaml"
        self.fixture.write(path, "buttons:\n- key: light_on\n  write: {dimmer: 1}\n- key: light_off\n  write: {dimmer: 0}\n- key: unknown_sensitive_123\n  write: {dimmer: 2}\npassword: another_sensitive_123\n")
        self.fixture.write("custom_components/connectlife/strings.json", json.dumps({"entity": {"button": {
            "light_on": {"name": "Light on"}, "light_off": {"name": "Light off"}}}}))
        _, _, files = self.fixture.build()
        source = files["erweiterungen/" + path].decode()
        self.assertIn("key: light_on", source)
        self.assertIn("key: light_off", source)
        buttons = json.loads(files["erweiterungen/custom_components/connectlife/strings.json"])["entity"]["button"]
        self.assertEqual(set(buttons), {"light_on", "light_off"})
        combined = b"\n".join(files.values())
        self.assertNotIn(b"unknown_sensitive_123", combined)
        self.assertNotIn(b"another_sensitive_123", combined)

    def test_real_credential_matching_public_command_is_still_masked(self):
        self.fixture.write("secrets.yaml", "api: light_on\n")
        self.fixture.write("custom_components/connectlife/data_dictionaries/009-999.yaml", "buttons:\n- key: light_on\n  write: {dimmer: 1}\n")
        _, _, files = self.fixture.build()
        self.assertNotIn(b"light_on", b"\n".join(files.values()))

    def test_public_command_exception_requires_exact_source_path_and_button_shape(self):
        for path, source in (
            ("custom_components/other/data_dictionaries/009-999.yaml", "buttons:\n- key: light_on\n  write: {dimmer: 1}\n"),
            ("custom_components/connectlife/data_dictionaries/009-999.yaml", "buttons:\n- key: light_on\n"),
        ):
            with self.subTest(path=path):
                redactor = test_export.Redactor()
                result = redactor.source(source, ".yaml", path)
                self.assertNotIn("light_on", result)

    def test_functional_nested_media_and_backup_directories_are_collected(self):
        self.fixture.write("media/private.txt", "PRIVATE_ROOT_MEDIA")
        self.fixture.write("backup/private.txt", "PRIVATE_ROOT_BACKUP")
        for name in ("media", "backup", "tts"):
            self.fixture.write("custom_components/example/" + name + "/helper.py", "ENABLED = True\n")
        _, _, files = self.fixture.build()
        for name in ("media", "backup", "tts"):
            self.assertIn("erweiterungen/custom_components/example/" + name + "/helper.py", files)
        self.assertNotIn(b"PRIVATE_ROOT", b"\n".join(files.values()))

    def test_unknown_format_is_a_gap_and_not_an_unchecked_copy(self):
        self.fixture.write("custom_components/example/new.future", "private_extra_data_123\n")
        _, result, files = self.fixture.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertIn("Nicht unterstütztes Dateiformat", files["EXPORTBERICHT.md"].decode())
        self.assertNotIn(b"private_extra_data_123", b"\n".join(files.values()))

    def test_lovelace_resource_storage_is_preserved_with_masked_url(self):
        self.fixture.write(".storage/lovelace_resources", json.dumps({"version": 1, "minor_version": 1,
            "key": "lovelace_resources", "data": {"items": [{"url": "/local/card.js?api_key=private_url_123", "type": "module"}]}}))
        _, _, files = self.fixture.build()
        result = json.loads(files["konfiguration/.storage/lovelace_resources"])
        self.assertEqual(result["key"], "lovelace_resources")
        self.assertNotIn(b"private_url_123", b"\n".join(files.values()))


class ConfigNotFound(Exception):
    pass


def collector_hass(dashboards=None, records=None):
    module = test_collector_view.module
    for name, attr in [("entity", "entities"), ("device", "devices"), ("area", "areas"), ("floor", "floors"), ("label", "labels")]:
        module("homeassistant.helpers." + name + "_registry", async_get=lambda hass, a=attr: types.SimpleNamespace(**{a: {}}))
    module("homeassistant.helpers.issue_registry", async_get=lambda hass: types.SimpleNamespace(issues={}))
    module("homeassistant.helpers.system_info", async_get_system_info=lambda hass: {"version": "synthetic"})
    module("homeassistant.helpers.service", async_get_all_descriptions=lambda hass: {}, async_register_admin_service=lambda *args, **kwargs: None)
    module("homeassistant.components.lovelace.const", ConfigNotFound=ConfigNotFound)
    return types.SimpleNamespace(
        config=types.SimpleNamespace(as_dict=lambda: {"time_zone": "UTC"}, time_zone="UTC", recovery_mode=False),
        states=types.SimpleNamespace(async_all=lambda: []), services=test_collector_view.Services(),
        config_entries=types.SimpleNamespace(async_entries=lambda: []),
        data={"lovelace": types.SimpleNamespace(dashboards=dashboards or {"main": test_collector_view.Dashboard()},
              resources=test_collector_view.ResourceYAMLCollection()),
              "system_log": types.SimpleNamespace(records=types.SimpleNamespace(to_list=lambda: records or []))})


class AutoDashboard(test_collector_view.Dashboard):
    config = None

    async def async_load(self, force):
        raise ConfigNotFound()

    async def async_get_info(self):
        return {"mode": "auto-gen"}


class LiveRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_generated_overview_is_explicit_without_false_load_error(self):
        hass = collector_hass({None: AutoDashboard(), "main": test_collector_view.Dashboard()})
        snapshot = await collect(hass)
        self.assertEqual(snapshot["files"]["dashboards/standard.json"]["status"], "automatisch_generiert")
        rows = snapshot["files"]["inventar/dashboards.json"]
        self.assertFalse(rows[0]["geladen"])
        self.assertTrue(rows[1]["geladen"])
        self.assertFalse(any(x["bereich"] == "dashboards/standard.json" for x in snapshot["issues"]))

    async def test_missing_config_is_not_suppressed_without_auto_generation_proof(self):
        class Broken(AutoDashboard):
            async def async_get_info(self):
                return {"mode": "storage"}
        for dashboard, recovery in ((Broken(), False), (AutoDashboard(), True)):
            with self.subTest(recovery=recovery):
                hass = collector_hass({"main": dashboard})
                hass.config.recovery_mode = recovery
                snapshot = await collect(hass)
                self.assertTrue(any(x["bereich"] == "dashboards/main.json" for x in snapshot["issues"]))
                self.assertNotIn("dashboards/main.json", snapshot["files"])

    async def test_live_error_buffer_is_bounded_read_only_and_redacted_in_real_zip(self):
        records = [{"message": ['failed password="quoted_private_123" api_key=bare_private_123 https://example.invalid/?token=url_private_123'],
                    "level": "ERROR", "count": 2}] * 105
        hass = collector_hass(records=records)
        snapshot = await collect(hass)
        self.assertEqual(len(snapshot["files"]["diagnose/system_log.json"]["entries"]), 100)
        self.assertEqual(snapshot["files"]["diagnose/system_log.json"]["weitere_nicht_erfasst"], 5)
        self.assertEqual(hass.services.calls, [])
        fixture = test_export.ExportTests()
        fixture.setUp()
        try:
            fixture.snapshot = snapshot
            _, _, files = fixture.build()
            for secret in (b"quoted_private_123", b"bare_private_123", b"url_private_123"):
                self.assertNotIn(secret, b"\n".join(files.values()))
            self.assertIn(b"[MASKIERT]", files["diagnose/system_log.json"])
        finally:
            fixture.tearDown()


class HistoryRegressionTests(unittest.IsolatedAsyncioTestCase):
    def recorder(self, producer):
        async def job(fn):
            return fn()
        test_collector_view.module("homeassistant.components.recorder", get_instance=lambda hass: types.SimpleNamespace(async_add_executor_job=job))
        test_collector_view.module("homeassistant.components.recorder.history", get_significant_states=producer)

    async def test_fast_counter_does_not_crowd_out_older_door_event(self):
        calls = []
        def rows(hass, begin, end, **kwargs):
            calls.append(kwargs["entity_ids"])
            result = {}
            if "sensor.fast" in kwargs["entity_ids"]:
                result["sensor.fast"] = [{"state": str(i)} for i in range(50)]
            if len(calls) == 4:
                result["binary_sensor.door"] = [{"state": "on"}]
            return result
        self.recorder(rows)
        events = []
        result, incomplete = await history_snapshot(object(), ["sensor.fast", "binary_sensor.door"], lambda *args, **kwargs: events.append(args), hours=1, row_limit=10)
        self.assertTrue(incomplete)
        self.assertEqual([s["state"] for s in result["states"]["sensor.fast"]], ["45", "46", "47", "48", "49"])
        self.assertEqual(result["states"]["binary_sensor.door"], [{"state": "on"}])
        self.assertEqual(result["gekürzte_entitaeten"], ["sensor.fast"])
        self.assertNotIn("sensor.fast", calls[1])
        self.assertEqual(sum(result["zeilen_je_entitaet"].values()), 6)
        self.assertEqual(len(calls), 4)

    async def test_empty_history_is_distinct_from_timed_out_history(self):
        self.recorder(lambda *args, **kwargs: {})
        result, incomplete = await history_snapshot(object(), ["binary_sensor.door"], lambda *args, **kwargs: None, hours=1)
        self.assertFalse(incomplete)
        self.assertEqual(result["status"], "erfolgreich")
        self.assertEqual(result["zeilen_je_entitaet"]["binary_sensor.door"], 0)
        def timeout(*args, **kwargs):
            raise TimeoutError()
        self.recorder(timeout)
        result, incomplete = await history_snapshot(object(), ["binary_sensor.door"], lambda *args, **kwargs: None, hours=1)
        self.assertTrue(incomplete)
        self.assertEqual(result["status"], "teilweise")


if __name__ == "__main__":
    unittest.main()
