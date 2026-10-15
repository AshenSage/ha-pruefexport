"""Privacy, bounded recommendation inputs and meaningful completeness status."""
import json
import types
import unittest
from unittest.mock import patch

import test_collector_view
import test_export
import test_review_regressions
from ha_pruefexport.collect import collect, select_history


class PrivacyAndStatusTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_export.ExportTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_short_alarm_codes_in_yaml_traces_and_runtime_are_masked(self):
        self.fixture.write("secrets.yaml", 'quoted_pin: "7482"\nnumeric_pin: 6391\n')
        self.fixture.write("automations.yaml", "- alias: Synthetic\n  actions:\n  - action: alarm_control_panel.alarm_disarm\n    data: {code: '7482'}\n  - service: alarm_control_panel.alarm_arm_away\n    data: {code: 6391}\n  - action: alarm_control_panel.alarm_disarm\n    data: {code: '8573'}\n  - action: alarm_control_panel.alarm_disarm\n    data: {code: !secret quoted_pin}\n")
        self.fixture.write(".storage/trace.saved_traces", json.dumps({"data": [{"params": {
            "domain": "alarm_control_panel", "service_data": {"code": "8573"}}}]}))
        self.fixture.snapshot["files"]["runtime/definitionen_script.json"] = [{"entity_id": "script.synthetic",
            "config": {"sequence": [{"action": "alarm_control_panel.alarm_disarm", "data": {"code": "9654"}}]}}]
        self.fixture.snapshot["files"]["runtime/copies.json"] = {"variable": "7482", "number": 6391}
        _, _, files = self.fixture.build()
        for name in ("konfiguration/automations.yaml", "konfiguration/.storage/trace.saved_traces",
                     "runtime/definitionen_script.json", "runtime/copies.json"):
            for pin in (b"7482", b"6391", b"8573", b"9654"):
                self.assertNotIn(pin, files[name], name)
        self.assertIn(b"!secret quoted_pin", files["konfiguration/automations.yaml"])

    def test_public_codes_templates_and_timestamp_substrings_remain_usable(self):
        self.fixture.write("secrets.yaml", 'pin: "2026"\n')
        self.fixture.write("automations.yaml", "- action: alarm_control_panel.alarm_disarm\n  data:\n    code: '{{ states(\"input_text.code\") }}'\n")
        self.fixture.snapshot["files"]["runtime/public.json"] = {"code": "public", "http_code": 200,
            "date": "2026-10-15T10:00:00Z", "entity_id": "sensor.counter_2026", "zero": 0, "on": "on"}
        _, _, files = self.fixture.build()
        public = json.loads(files["runtime/public.json"])
        self.assertEqual(public["code"], "public")
        self.assertEqual(public["http_code"], 200)
        self.assertEqual(public["date"], "2026-10-15T10:00:00Z")
        self.assertEqual(public["entity_id"], "sensor.counter_2026")
        self.assertEqual((public["zero"], public["on"]), (0, "on"))
        self.assertIn(b"states", files["konfiguration/automations.yaml"])

    def test_shared_yaml_mapping_is_masked_even_if_first_seen_outside_alarm_context(self):
        self.fixture.write("alias.yaml", "shared: &shared\n  code: '5829'\nactions:\n- action: alarm_control_panel.alarm_disarm\n  data: *shared\n- action: alarm_control_panel.alarm_arm_away\n  data: *shared\n")
        _, _, files = self.fixture.build()
        self.assertIn("konfiguration/alias.yaml", files)
        source = files["konfiguration/alias.yaml"]
        self.assertNotIn(b"5829", source)
        self.assertIn(b"*shared", source)

    def test_scope_notes_do_not_hide_real_gaps(self):
        self.fixture.snapshot["notes"] = [{"bereich": "Statistiken", "status": "hinweis", "grund": "Bewusst nicht erfasst"}]
        _, result, files = self.fixture.build()
        self.assertEqual((result["status"], result["issues"], result["notes"]), ("vollstaendig", 0, 1))
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(len(manifest["notes"]), 1)
        self.assertEqual(manifest["issues"], [])
        self.fixture.write("extra.future", "unchecked_source")
        _, result, files = self.fixture.build()
        self.assertEqual(result["status"], "teilweise")
        self.assertGreater(result["issues"], 0)
        self.assertIn("## Erfassungslücken", files["EXPORTBERICHT.md"].decode())
        self.assertIn("## Hinweise zum vorgesehenen Umfang", files["EXPORTBERICHT.md"].decode())

    def test_scope_note_secrets_are_masked_and_finally_checked(self):
        self.fixture.write("secrets.yaml", "api: private_note_secret_123\n")
        self.fixture.snapshot["notes"] = [{"bereich": "Note", "grund": "private_note_secret_123"}]
        _, _, files = self.fixture.build()
        self.assertNotIn(b"private_note_secret_123", b"\n".join(files.values()))


class SelectionTests(unittest.TestCase):
    def states(self, *entities):
        return [test_collector_view.State(entity, "off") for entity in entities]

    def test_automation_script_and_dashboard_share_slots_with_provenance(self):
        files = {"dashboards/main.json": {"entities": ["sensor.dashboard_1", "sensor.dashboard_2", "sensor.dashboard_3"]},
            "runtime/definitionen_automation.json": [{"entity_id": "automation.example", "config": {
                "trigger": {"entity_id": "binary_sensor.door"}}, "referenzierte_entitaeten": ["sensor.blueprint"]}],
            "runtime/definitionen_script.json": [{"entity_id": "script.example", "config": {
                "sequence": [{"condition": "{{ states('sensor.humidity') | float > 60 }}"}]}}]}
        states = self.states("sensor.dashboard_1", "sensor.dashboard_2", "sensor.dashboard_3", "binary_sensor.door", "sensor.blueprint", "sensor.humidity")
        result = select_history(states, files, limit=3)
        self.assertEqual(result["entity_ids"], ["binary_sensor.door", "sensor.humidity", "sensor.dashboard_1"])
        self.assertEqual(result["herkunft"]["sensor.blueprint"], ["automation.example"])
        self.assertIn("sensor.dashboard_2", result["weitere_nicht_erfasst"])
        self.assertEqual(result, select_history(list(reversed(states)), dict(reversed(list(files.items()))), limit=3))

    def test_private_domains_self_export_missing_ids_and_resource_text_are_excluded(self):
        ids = ["person.demo", "device_tracker.phone", "input_text.pin", "camera.demo", "sensor.ha_pruefexport", "binary_sensor.door"]
        files = {"dashboards/main.json": {"entities": ids + ["sensor.not_present"]},
                 "dashboards/ressourcen.json": {"url": "sensor.resource_only"}}
        result = select_history(self.states(*ids, "sensor.resource_only"), files)
        self.assertEqual(result["entity_ids"], ["binary_sensor.door"])
        self.assertEqual(result["ausgeschlossen"], sorted(ids[:-1]))
        self.assertNotIn("sensor.not_present", result["herkunft"])

    def test_duplicates_use_one_slot_and_keep_all_origins(self):
        files = {"dashboards/main.json": {"entity": "sensor.shared"},
            "runtime/definitionen_automation.json": [{"entity_id": "automation.example", "config": {"entity_id": "sensor.shared"}}]}
        result = select_history(self.states("sensor.shared"), files)
        self.assertEqual(result["entity_ids"], ["sensor.shared"])
        self.assertEqual(result["herkunft"]["sensor.shared"], ["automation.example", "dashboards/main.json"])


class LiveDefinitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_loaded_definitions_and_blueprint_references_feed_recorder_without_running_actions(self):
        hass = test_review_regressions.collector_hass()
        hass.states.async_all = lambda: [test_collector_view.State("binary_sensor.hidden_door", "off")]
        entity = types.SimpleNamespace(entity_id="automation.example", raw_config={"use_blueprint": {"input": {}}},
                                       referenced_entities={"binary_sensor.hidden_door"})
        hass.data["automation"] = types.SimpleNamespace(entities=[entity])
        async def history(hass, selection, report):
            self.assertEqual(selection, ["binary_sensor.hidden_door"])
            return {"status": "erfolgreich", "states": {}}, False
        with patch("ha_pruefexport.collect.history_snapshot", history):
            snapshot = await collect(hass)
        self.assertEqual(snapshot["files"]["runtime/definitionen_automation.json"][0]["referenzierte_entitaeten"], ["binary_sensor.hidden_door"])
        self.assertTrue(snapshot["notes"])
        self.assertEqual(hass.services.calls, [])
        self.assertFalse(any(x["bereich"] == "Ergänzende Diagnosen/Statistiken/externe Apps" for x in snapshot["issues"]))

    async def test_unreadable_definition_is_an_explicit_gap_and_others_continue(self):
        class Broken:
            entity_id = "script.broken"
            @property
            def raw_config(self):
                raise RuntimeError("private_provider_detail")
        hass = test_review_regressions.collector_hass()
        hass.data["script"] = types.SimpleNamespace(entities=[Broken(), types.SimpleNamespace(
            entity_id="script.good", raw_config={"sequence": []}, referenced_entities=set())])
        snapshot = await collect(hass)
        self.assertEqual(len(snapshot["files"]["runtime/definitionen_script.json"]), 1)
        self.assertTrue(any(x["bereich"] == "Definition script.broken" for x in snapshot["issues"]))
        self.assertNotIn("private_provider_detail", str(snapshot))


if __name__ == "__main__":
    unittest.main()
