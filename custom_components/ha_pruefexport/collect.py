"""Read HA's live objects. Optional API failures become explicit export gaps."""
from __future__ import annotations

import asyncio
import dataclasses
import importlib
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import partial
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from .exporter import utcnow
from .progress import ProgressReporter


def plain(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return {"seconds": value.total_seconds()}
    if isinstance(value, Enum):
        return plain(value.value)
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [plain(v) for v in value]
    # Registry entries expose this property; class lookup avoids probing a dynamic
    # compatibility __getattr__ on the registry collection itself.
    if getattr(type(value), "dict_repr", None) is not None:
        return plain(value.dict_repr)
    if hasattr(value, "as_dict"):
        return plain(value.as_dict())
    if dataclasses.is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    return {"nicht_exportierbar": type(value).__name__}


def registry_snapshot(items):
    if isinstance(items, Mapping):
        return plain(items)
    result = {}
    for item in items:
        row = plain(item)
        identifier = (row.get("entity_id") or row.get("id")) if isinstance(row, dict) else None
        if not isinstance(identifier, str) or identifier in result:
            raise ValueError("Registry-Eintrag ohne eindeutige Identität")
        result[identifier] = row
    return result


async def collect(hass, progress=None):
    started = utcnow()
    report = ProgressReporter(progress)
    report("HA-Zustände lesen", 2)
    files, issues = {}, []
    result = {"started": started, "files": files, "issues": issues, "local_references": []}

    def problem(name, error, status="teilweise"):
        # Never put exception messages in exports: providers may include a secret URL.
        issues.append({"bereich": name, "status": status, "grund": "Nicht erfasst: " + type(error).__name__})

    async def capture(name, producer):
        try:
            value = producer()
            if hasattr(value, "__await__"):
                value = await asyncio.wait_for(value, 45)
            files[name] = plain(value)
        except Exception as error:
            problem(name, error)

    states = hass.states.async_all()
    state_rows = []
    for state in states:
        row = plain(state)
        if not isinstance(row, dict) or "entity_id" not in row:
            problem("runtime/zustaende.json", TypeError())
            continue
        if state.entity_id.startswith("input_text."):
            row["state"] = "[MASKIERT: input_text-Inhalt]"
        reported = getattr(state, "last_reported", None)
        row["last_reported"] = reported.isoformat() if reported else None
        state_rows.append(row)
    files["runtime/zustaende.json"] = {"erfasst_utc": utcnow(), "states": state_rows,
                                         "hinweis": "input_text-Inhalte absichtlich maskiert; last_reported ist kein externer Quellenzeitstempel"}
    report("Systemdaten lesen", 4)
    await capture("runtime/ha_konfiguration.json", hass.config.as_dict)
    try:
        module = importlib.import_module("homeassistant.helpers.system_info")
        await capture("runtime/system_info.json", lambda: module.async_get_system_info(hass))
    except Exception as error:
        problem("runtime/system_info.json", error)
    files["runtime/exportzeit.json"] = {"start_utc": started, "ha_timezone": hass.config.time_zone,
                                         "start_ha": datetime.fromisoformat(started).astimezone(ZoneInfo(hass.config.time_zone)).isoformat()}
    files["runtime/dienste.json"] = plain(hass.services.async_services())
    try:
        module = importlib.import_module("homeassistant.helpers.service")
        await capture("runtime/dienstbeschreibungen.json", lambda: module.async_get_all_descriptions(hass))
    except Exception as error:
        problem("runtime/dienstbeschreibungen.json", error)
    report("Integrationen lesen", 6)
    entries = hass.config_entries.async_entries()
    files["inventar/integrationen.json"] = [
        {"entry_id": entry.entry_id, "domain": entry.domain, "title": entry.title,
         "source": entry.source, "state": plain(entry.state), "disabled_by": plain(entry.disabled_by),
         "version": entry.version, "data": plain(entry.data), "options": plain(entry.options)} for entry in entries]

    for index, (name, attribute) in enumerate([("entity", "entities"), ("device", "devices"), ("area", "areas"),
                            ("floor", "floors"), ("label", "labels")]):
        report("Geräte und Entitäten lesen", 7 + index)
        try:
            module = importlib.import_module("homeassistant.helpers." + name + "_registry")
            registry = module.async_get(hass)
            files["runtime/registry_" + name + ".json"] = registry_snapshot(getattr(registry, attribute))
        except Exception as error:
            problem("Registry " + name, error)
    report("Diagnosehinweise lesen", 12)
    try:
        module = importlib.import_module("homeassistant.helpers.issue_registry")
        files["diagnose/repairs.json"] = plain(module.async_get(hass).issues)
    except Exception as error:
        problem("Repairs", error)

    # Read the in-memory Lovelace managers; disk sources are supplementary, not a substitute.
    report("Dashboards lesen", 14)
    try:
        lovelace = hass.data["lovelace"]
        dashboards = lovelace.get("dashboards") if isinstance(lovelace, dict) else lovelace.dashboards
        resources = lovelace.get("resources") if isinstance(lovelace, dict) else lovelace.resources
        dashboard_rows = []
        for index, (key, dashboard) in enumerate(dashboards.items()):
            identifier = "standard" if key is None else str(key)
            filename = "dashboards/" + re.sub(r"[^a-zA-Z0-9_.-]", "_", identifier) + ".json"
            # Avoid silent collisions in renamed dashboard URL paths.
            if filename in files:
                raise ValueError("dashboard filename collision")
            await capture(filename, lambda d=dashboard: d.async_load(False))
            dashboard_rows.append({"url_path": key, "archivpfad": filename,
                                   "manager_type": type(dashboard).__name__, "geladen": filename in files,
                                   "einstellungen": plain(getattr(dashboard, "config", {}))})
            config = getattr(dashboard, "config", {})
            if isinstance(config, dict) and isinstance(config.get("filename"), str):
                result["local_references"].append(config["filename"])
            report("Dashboards lesen", 14 + 4 * (index + 1) / max(1, len(dashboards)), index + 1, len(dashboards), "Dashboards")
        files["inventar/dashboards.json"] = dashboard_rows
        if not dashboard_rows:
            problem("Dashboards", ValueError())
        if resources is not None:
            if type(resources).__name__ == "ResourceStorageCollection":
                await resources.async_load()
            files["dashboards/ressourcen.json"] = plain(resources.async_items())
        else:
            problem("Lovelace Ressourcen", ValueError())
    except Exception as error:
        problem("Live-Dashboards/Ressourcen", error)

    report("Dashboard-Verweise lesen", 19)
    # Extract local resource paths and blueprint references. These are checked by the worker.
    def references(value):
        if isinstance(value, dict):
            if isinstance(value.get("use_blueprint"), dict):
                path = value["use_blueprint"].get("path")
                if isinstance(path, str):
                    for kind in ("automation", "script"):
                        candidate = "blueprints/" + kind + "/" + path
                        if __import__("pathlib").Path(hass.config.path(candidate)).is_file():
                            result["local_references"].append(candidate)
                            break
                    else:
                        issues.append({"bereich": "Blueprint", "status": "teilweise", "grund": "Referenzierter Blueprint fehlt"})
            for item in value.values():
                references(item)
        elif isinstance(value, list):
            for item in value:
                references(item)
        elif isinstance(value, str):
            if value.startswith("/local/"):
                result["local_references"].append("www/" + unquote(urlsplit(value).path[7:]))
            elif value.startswith("/hacsfiles/"):
                result["local_references"].append("www/community/" + unquote(urlsplit(value).path[len("/hacsfiles/"):]))
    for name, value in list(files.items()):
        if name.startswith(("dashboards/", "inventar/integrationen")):
            references(value)
    result["local_references"] = sorted(set(result["local_references"]))

    # The only invoked services are explicitly read-only response services.
    semaphore = asyncio.Semaphore(3)
    completed_responses = 0
    async def response(domain, action, entity, data, name):
        nonlocal completed_responses
        async with semaphore:
            try:
                if not hass.services.has_service(domain, action):
                    files[name] = {"entity_id": entity, "status": "nicht_unterstuetzt", "response": None}
                    problem(name, NotImplementedError())
                    return
                answer = await asyncio.wait_for(hass.services.async_call(domain, action, data,
                    target={"entity_id": entity}, blocking=True, return_response=True), 30)
                files[name] = {"entity_id": entity, "abgerufen_utc": utcnow(), "status": "erfolgreich", "response": plain(answer)}
            except Exception as error:
                files[name] = {"entity_id": entity, "status": "fehlgeschlagen", "response": None, "fehlerart": type(error).__name__}
                problem(name, error)
            finally:
                completed_responses += 1
                report("Wetter und Kalender lesen", 20 + 3 * completed_responses / max(1, len(calls)), completed_responses, len(calls), "Abrufe")
    calls = []
    weather = [s.entity_id for s in states if s.entity_id.startswith("weather.")]
    calendars = [s.entity_id for s in states if s.entity_id.startswith("calendar.")]
    if len(weather) > 10 or len(calendars) > 20:
        issues.append({"bereich": "Forecast/Kalender", "status": "teilweise", "grund": "Limit 10 Wetterentitäten/20 Kalender erreicht"})
    for entity in weather[:10]:
        for kind in ("hourly", "daily"):
            calls.append(response("weather", "get_forecasts", entity, {"type": kind}, "diagnose/forecast/" + entity + "_" + kind + ".json"))
    today = datetime.now(ZoneInfo(hass.config.time_zone)).replace(hour=0, minute=0, second=0, microsecond=0)
    for entity in calendars[:20]:
        calls.append(response("calendar", "get_events", entity,
                     {"start_date_time": today.isoformat(), "end_date_time": (today + timedelta(days=90)).isoformat()},
                     "diagnose/kalender/" + entity + ".json"))
    if calls:
        report("Wetter und Kalender lesen", 20, 0, len(calls), "Abrufe")
        await asyncio.gather(*calls)

    # Bounded recorder history; metadata describes the selection and any omitted entities.
    referenced = set()
    for name, data in files.items():
        if name.startswith("dashboards/"):
            import json
            referenced.update(re.findall(r"\b[a-z_]+\.[a-zA-Z0-9_]+\b", json.dumps(data)))
    eligible = sorted(s.entity_id for s in states if s.entity_id in referenced and not s.entity_id.startswith(("input_text.", "camera.", "person.", "device_tracker.")))
    selection = eligible[:100]
    files["diagnose/verlauf_auswahl.json"] = {"entity_ids": selection, "weitere_nicht_erfasst": eligible[100:], "stunden": 48,
                                               "hinweis": "Nur im Dashboard ausdrücklich genannte Entitäten; dynamische Filter können zusätzliche Entitäten verwenden"}
    if len(eligible) > 100:
        problem("Verlauf", ValueError())
    if selection:
        report("Verlauf lesen", 23, 0, unit="Verlaufzeilen")
        try:
            recorder = importlib.import_module("homeassistant.components.recorder")
            history = importlib.import_module("homeassistant.components.recorder.history")
            end = datetime.now(timezone.utc)
            cursor, earliest = end, end - timedelta(hours=48)
            data, left, truncated = {}, 10000, False
            deadline = asyncio.get_running_loop().time() + 40
            while cursor > earliest and left > 0:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                begin = max(earliest, cursor - timedelta(minutes=15))
                job = partial(history.get_significant_states, hass, begin, cursor,
                              entity_ids=selection, include_start_time_state=False,
                              significant_changes_only=True, minimal_response=True, no_attributes=True)
                try:
                    chunk = await asyncio.wait_for(recorder.get_instance(hass).async_add_executor_job(job), remaining)
                except TimeoutError:
                    break
                for key, values in chunk.items():
                    if len(values) > left:
                        truncated = True
                    selected = values[-left:] if left else []
                    data.setdefault(key, [])[:0] = plain(selected)
                    left -= len(selected)
                cursor = begin
                covered = (end - cursor).total_seconds() / (48 * 3600)
                report("Verlauf lesen", 23 + 6 * max(covered, (10000 - left) / 10000), 10000 - left, unit="Verlaufzeilen")
            incomplete = cursor > earliest or truncated
            if incomplete:
                issues.append({"bereich": "Verlauf", "status": "teilweise", "grund": "48-Stunden-Verlauf wegen 10000-Zeilen-/40-Sekunden-Limit nur teilweise erfasst"})
            files["diagnose/verlauf.json"] = {"angefordert_von_utc": earliest.isoformat(), "bis_utc": end.isoformat(),
                                               "erfasst_ab_utc": cursor.isoformat(), "status": "teilweise" if incomplete else "erfolgreich",
                                               "hinweis": "Nur Zustandsänderungen, ohne Attribute; Einheiten stehen im aktuellen Zustandsauszug",
                                               "states": data}
        except Exception as error:
            problem("Verlauf", error)

    # Diagnostics contain integration-specific privacy-sensitive information. Record support,
    # but do not blindly call every custom provider in a generic audit exporter.
    files["diagnose/umfang.json"] = {
        "integration_diagnosen": "nicht automatisch abgerufen; Anbieterformat/Maskierung muss je Integration geprüft werden",
        "statistikdaten": "nicht automatisch abgerufen; bei Statistik-/Energiekarten gezielt ergänzen",
        "traces": "Vorhandene .storage/trace.saved_traces wird maskiert mitgesammelt; keine neue Trace-Ausführung",
        "externe_apps": "Nur unter /config vorhandene Quellen; keine Supervisor-/App-/Controller-Konfiguration ausserhalb dieses Bereichs",
        "system_logs": "Vorhandene lokale HA-Logdateien jeweils letzte 256 KiB; kein Supervisor-Logzugriff",
        "quellen_cache": "Vorhandene JSON-/Textquellen unter /config; keine beliebigen unbekannten Dienste"}
    issues.append({"bereich": "Ergänzende Diagnosen/Statistiken/externe Apps", "status": "nicht_ausgewertet",
                   "grund": "Keine pauschale Erfassung; Bedarf anhand Dashboard und Integrationen im Methodencheck klären"})
    files["runtime/snapshot_zeitfenster.json"] = {"start_utc": started, "ende_utc": utcnow(), "atomar": False}
    report("HA-Daten gelesen", 30)
    return result
