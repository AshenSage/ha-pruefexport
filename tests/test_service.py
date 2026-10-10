"""Exercise the real service schema and actual card payload with both HA engines."""
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

import probatio
import voluptuous
import yaml

import test_collector_view
import test_export
from ha_pruefexport.const import VERSION
from ha_pruefexport.manager import ExportManager


def load_entry(engine, source=None):
    entry = types.ModuleType("ha_pruefexport.schema_test")
    entry.__package__ = "ha_pruefexport"
    # HA 2026.9+ aliases the legacy import to Probatio; older HA uses voluptuous.
    with patch.dict("sys.modules", {"voluptuous": engine}):
        if source is None:
            source = (test_export.PACKAGE / "__init__.py").read_text()
        exec(compile(source, str(test_export.PACKAGE / "__init__.py"), "exec"), entry.__dict__)
    return entry


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def registered(self, engine, source=None):
        entry = load_entry(engine, source)
        registered = {}
        # Match HA's administrator-service helper default: extra fields rejected.
        def register(hass, domain, action, handler, schema=engine.Schema({}, extra=engine.PREVENT_EXTRA)):
            registered.update(domain=domain, action=action, handler=handler, schema=schema)
        manager = types.SimpleNamespace(start=unittest.mock.Mock())
        hass = types.SimpleNamespace(data={"ha_pruefexport": manager}, http=types.SimpleNamespace(register_view=lambda view: None))
        with patch.object(entry, "async_register_admin_service", register):
            self.assertTrue(await entry.async_setup(hass, {}))
        return registered, manager, hass

    async def test_actual_card_payload_reaches_manager_with_both_engines(self):
        card = yaml.safe_load((test_export.ROOT / "system_pruefexport_karte.yaml").read_text())
        action = card["cards"][1]["cards"][0]["tap_action"]
        for engine in (voluptuous, probatio):
            with self.subTest(engine=engine.__name__):
                reg, manager, hass = await self.registered(engine)
                self.assertEqual(action["service"], reg["domain"] + "." + reg["action"])
                data = reg["schema"](action["service_data"])
                await reg["handler"](types.SimpleNamespace(data=data))
                manager.start.assert_called_once_with("methode")

    async def test_omitted_mode_defaults_to_method(self):
        for engine in (voluptuous, probatio):
            reg, manager, hass = await self.registered(engine)
            await reg["handler"](types.SimpleNamespace(data=reg["schema"]({})))
            manager.start.assert_called_once_with("methode")

    async def test_entire_audit_mode_reaches_manager(self):
        for engine in (voluptuous, probatio):
            reg, manager, hass = await self.registered(engine)
            await reg["handler"](types.SimpleNamespace(data=reg["schema"]({"pruefmodus": "gesamt"})))
            manager.start.assert_called_once_with("gesamt")

    async def test_invalid_values_rejected_before_manager(self):
        for engine in (voluptuous, probatio):
            reg, manager, hass = await self.registered(engine)
            for value in (None, True, 0, "", "Methode", "Nur Exportmethode prüfen", [], {}):
                with self.subTest(engine=engine.__name__, value=value):
                    with self.assertRaises(engine.Invalid):
                        reg["schema"]({"pruefmodus": value})
            manager.start.assert_not_called()

    async def test_unknown_field_rejected(self):
        for engine in (voluptuous, probatio):
            reg, manager, hass = await self.registered(engine)
            with self.assertRaises(engine.Invalid):
                reg["schema"]({"pruefmodus": "methode", "unexpected": "value"})
            manager.start.assert_not_called()

    async def test_missing_integration_has_clear_error(self):
        reg, manager, hass = await self.registered(probatio)
        hass.data.clear()
        with self.assertRaisesRegex(test_export.exceptions.HomeAssistantError, "Integration.*einrichten"):
            await reg["handler"](types.SimpleNamespace(data=reg["schema"]({})))
        manager.start.assert_not_called()


class ConfigPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_config_root_is_taken_from_ha_for_either_directory_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("config", "homeassistant"):
                with self.subTest(directory=name):
                    root = pathlib.Path(temporary) / name
                    root.mkdir()
                    (root / "configuration.yaml").write_text("default_config:\n")
                    manager = ExportManager(test_export.FakeHass(root))
                    await manager.async_load()
                    self.assertEqual(manager.root, root)
                    self.assertEqual(manager.private, root / ".ha_pruefexport")
                    self.assertTrue(manager.private.is_dir())
                    await manager.async_stop()

    async def test_exported_version_matches_package(self):
        package_version = json.loads((test_export.PACKAGE / "manifest.json").read_text())["version"]
        self.assertEqual(VERSION, package_version)
        case = test_export.ExportTests()
        case.setUp()
        try:
            builder, result, files = case.build()
            self.assertEqual(json.loads(files["manifest.json"])["exporter_version"], package_version)
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
