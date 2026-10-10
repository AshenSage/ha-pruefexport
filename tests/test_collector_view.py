"""API doubles: runtime provenance, read-only service allowlist, download restrictions."""
import asyncio
import importlib.util
import pathlib
import sys
import types
import unittest
from datetime import datetime, timezone

import test_export
from ha_pruefexport.collect import collect, registry_snapshot
from ha_pruefexport.manager import ExportManager


def module(name, **attributes):
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    sys.modules[name] = result
    return result


class State:
    def __init__(self, entity_id, value):
        self.entity_id, self.value = entity_id, value
        self.last_reported = datetime(2026, 1, 15, 6, tzinfo=timezone.utc)

    def as_dict(self):
        return {"entity_id": self.entity_id, "state": self.value, "attributes": {"unit_of_measurement": "km/h"},
                "last_changed": "2026-01-01T00:00:00+00:00", "last_updated": "2026-01-15T05:59:00+00:00"}


class ResourceYAMLCollection:
    def async_items(self):
        return [{"url": "/local/card.js?v=1", "type": "module"},
                {"url": "/hacsfiles/custom-card/custom-card.js?hacstag=123", "type": "module"}]

    async def async_load(self, data):
        raise AssertionError("Must not reload already-loaded YAML collection without its source")


class Dashboard:
    config = {"mode": "storage", "title": "Aktuell eingebaut"}

    async def async_load(self, force):
        return {"views": [{"title": "Live", "cards": [{"entity": "sensor.real"}]}]}


class Services:
    def __init__(self):
        self.calls = []

    def async_services(self):
        return {"weather": {"get_forecasts": {}}, "calendar": {"get_events": {}}}

    def has_service(self, domain, action):
        return True

    async def async_call(self, domain, action, data, **kwargs):
        self.calls.append((domain, action, data, kwargs))
        if domain == "weather" and data["type"] == "hourly":
            raise RuntimeError("secret_provider_url")
        return {kwargs["target"]["entity_id"]: {"forecast" if domain == "weather" else "events": []}}


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_iterable_device_registry_avoids_mapping_probe(self):
        class Entry:
            @property
            def dict_repr(self):
                return {"id": "device_demo", "name": "Kamera", "config_entry_id": "entry_demo"}
        class Devices:
            def __iter__(self):
                return iter([Entry()])
            def __getattr__(self, name):
                raise AssertionError("Deprecated mapping or dynamic attribute probe: " + name)
        data = registry_snapshot(Devices())
        self.assertEqual(data["device_demo"]["name"], "Kamera")
        self.assertEqual(data["device_demo"]["config_entry_id"], "entry_demo")

    async def test_registry_without_identity_or_duplicate_is_not_silent_success(self):
        for entries in ([{"name": "unnamed"}], [{"id": "same"}, {"id": "same"}]):
            with self.assertRaises(ValueError):
                registry_snapshot(entries)

    async def test_live_metadata_masking_empty_vs_error_and_allowlist(self):
        for name, attr in [("entity", "entities"), ("device", "devices"), ("area", "areas"), ("floor", "floors"), ("label", "labels")]:
            reg = types.SimpleNamespace(**{attr: {"real": {"name": name}}})
            module("homeassistant.helpers." + name + "_registry", async_get=lambda hass, r=reg: r)
        module("homeassistant.helpers.issue_registry", async_get=lambda hass: types.SimpleNamespace(issues={}))
        async def info(hass):
            return {"version": "offline-double", "installation_type": "Home Assistant OS"}
        async def descriptions(hass):
            return {"weather": {"get_forecasts": {"fields": {"type": {}}}}}
        module("homeassistant.helpers.system_info", async_get_system_info=info)
        module("homeassistant.helpers.service", async_get_all_descriptions=descriptions,
               async_register_admin_service=lambda *args: None)
        states = [State("sensor.real", "0"), State("input_text.alarm_pin", "1234"), State("weather.actual", "sunny"), State("calendar.actual", "off")]
        services = Services()
        config = types.SimpleNamespace(as_dict=lambda: {"time_zone": "UTC"}, time_zone="UTC", path=lambda p="": "/not_used/" + p)
        hass = types.SimpleNamespace(config=config, states=types.SimpleNamespace(async_all=lambda: states), services=services,
                                     config_entries=types.SimpleNamespace(async_entries=lambda: []),
                                     data={"lovelace": types.SimpleNamespace(dashboards={"main": Dashboard()}, resources=ResourceYAMLCollection())})
        progress = []
        data = await collect(hass, progress=progress.append)
        files = data["files"]
        self.assertEqual(files["runtime/zustaende.json"]["states"][0]["state"], "0")
        self.assertIn("MASKIERT", files["runtime/zustaende.json"]["states"][1]["state"])
        self.assertEqual(files["runtime/zustaende.json"]["states"][0]["last_reported"], "2026-01-15T06:00:00+00:00")
        self.assertEqual(files["dashboards/main.json"]["views"][0]["title"], "Live")
        self.assertEqual(data["local_references"], ["www/card.js", "www/community/custom-card/custom-card.js"])
        self.assertEqual(files["diagnose/forecast/weather.actual_hourly.json"]["status"], "fehlgeschlagen")
        self.assertIsNone(files["diagnose/forecast/weather.actual_hourly.json"]["response"])
        self.assertEqual(files["diagnose/forecast/weather.actual_daily.json"]["status"], "erfolgreich")
        self.assertEqual(len(services.calls), 3)
        self.assertTrue(all((domain, action) in {("weather", "get_forecasts"), ("calendar", "get_events")} for domain, action, _, _ in services.calls))
        self.assertNotIn("secret_provider_url", str(data))
        self.assertEqual(progress[-1]["progress_pct"], 30)
        self.assertEqual([p["progress_pct"] for p in progress], sorted(p["progress_pct"] for p in progress))
        responses = [p for p in progress if p["phase"] == "Wetter und Kalender lesen"]
        self.assertEqual(responses[-1]["processed"], 3)
        self.assertEqual(responses[-1]["total"], 3)
        self.assertNotIn("secret_provider_url", str(progress))


# Import only the route/init module with documented HA hooks stubbed.
HTTP_KEY = object()
USER_KEY = "hass_user"
http_view = module("homeassistant.components.http", HomeAssistantView=object, KEY_HASS=HTTP_KEY, KEY_HASS_USER=USER_KEY)
module("homeassistant.const", EVENT_HOMEASSISTANT_STOP="stop", Platform=types.SimpleNamespace(SENSOR="sensor"))
module("homeassistant.helpers.service", async_register_admin_service=lambda *args: None)
spec = importlib.util.spec_from_file_location("ha_pruefexport.entry", test_export.PACKAGE / "__init__.py")
entry = importlib.util.module_from_spec(spec)
entry.__package__ = "ha_pruefexport"
spec.loader.exec_module(entry)
from aiohttp import web


class Request(dict):
    def __init__(self, manager, user):
        super().__init__({USER_KEY: user})
        manager.hass.data = {"ha_pruefexport": manager}
        self.app = {HTTP_KEY: manager.hass}


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_export.ManagerTests.asyncSetUp
    asyncTearDown = test_export.ManagerTests.asyncTearDown

    async def test_server_admin_header_and_path(self):
        name = "ha_pruefexport_20260115_060000_abcdef12.zip"
        (self.manager.private / name).write_bytes(b"fixture")
        view = entry.DownloadView()
        self.assertTrue(view.requires_auth)
        for user in (None, types.SimpleNamespace(is_admin=False)):
            with self.assertRaises(web.HTTPForbidden):
                await view.get(Request(self.manager, user), name)
        admin = types.SimpleNamespace(is_admin=True)
        response = await view.get(Request(self.manager, admin), name)
        self.assertEqual(response.headers["Content-Type"], "application/zip")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        with self.assertRaises(web.HTTPNotFound):
            await view.get(Request(self.manager, admin), "../configuration.yaml")
        (self.manager.private / name).unlink()
        (self.manager.private / name).symlink_to(self.root / "configuration.yaml")
        with self.assertRaises(web.HTTPNotFound):
            await view.get(Request(self.manager, admin), name)
