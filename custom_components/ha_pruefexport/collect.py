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


ENTITY_REF = re.compile(r"\b[a-z_]+\.[a-zA-Z0-9_]+\b")
PRIVATE_HISTORY_DOMAINS = ("input_text.", "camera.", "person.", "device_tracker.")


def entity_references(value):
    """Find literal entity IDs, including literals inside templates; never render them."""
    if isinstance(value, Mapping):
        return set().union(*(entity_references(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return set().union(*(entity_references(v) for v in value)) if value else set()
    return set(ENTITY_REF.findall(value)) if isinstance(value, str) else set()


def select_history(states, files, limit=100):
    """Share the bounded selection between automations, scripts and dashboards."""
    available = {s.entity_id for s in states}
    origins, buckets = {}, {"automation": set(), "script": set(), "dashboard": set()}
    for name, value in files.items():
        if name.startswith("dashboards/") and name != "dashboards/ressourcen.json":
            groups = [("dashboard", name, entity_references(value))]
        elif name in {"runtime/definitionen_automation.json", "runtime/definitionen_script.json"}:
            category = "automation" if name.endswith("_automation.json") else "script"
            groups = [(category, row["entity_id"], entity_references(row)) for row in value]
        else:
            continue
        for category, origin, refs in groups:
            for entity in refs & available:
                origins.setdefault(entity, set()).add(origin)
                if not entity.startswith(PRIVATE_HISTORY_DOMAINS) and entity != "sensor.ha_pruefexport":
                    buckets[category].add(entity)
    # Round-robin prevents a large dashboard or automation set from using all slots.
    queues = {key: iter(sorted(values)) for key, values in buckets.items()}
    selected = []
    while queues and len(selected) < limit:
        for key, queue in list(queues.items()):
            entity = next(queue, None)
            if entity is None:
                del queues[key]
            elif entity not in selected:
                selected.append(entity)
            if len(selected) == limit:
                break
    eligible = set().union(*buckets.values())
    return {"entity_ids": selected, "weitere_nicht_erfasst": sorted(eligible - set(selected)),
            "ausgeschlossen": sorted(set(origins) - eligible), "stunden": 48, "entitaetenlimit": limit,
            "herkunft": {entity: sorted(origins[entity]) for entity in sorted(origins)},
            "hinweis": "Abwechselnd Automationen, Skripte und Dashboards; nur vorhandene, ausdrücklich referenzierte Entitäten. HA-Referenzen berücksichtigen aufgelöste Blueprints. Dynamische Templates, Geräte-/Bereichsziele und nicht geladene Definitionen können zusätzliche Entitäten verwenden. Keine Personen-/Tracker-/Kamera-/input_text-Verläufe; kein eigener Exportstatus."}


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


async def history_snapshot(hass, selection, report, *, hours=48, row_limit=10000, timeout=40):
    """Bound history fairly per entity so fast counters cannot crowd out doors."""
    recorder = importlib.import_module("homeassistant.components.recorder")
    history = importlib.import_module("homeassistant.components.recorder.history")
    end = datetime.now(timezone.utc)
    cursor, earliest = end, end - timedelta(hours=hours)
    quota = max(1, row_limit // len(selection))
    data, counts, limited = {}, dict.fromkeys(selection, 0), set()
    deadline = asyncio.get_running_loop().time() + timeout
    while cursor > earliest:
        active = [entity for entity in selection if counts[entity] < quota]
        remaining = deadline - asyncio.get_running_loop().time()
        if not active or remaining <= 0:
            break
        begin = max(earliest, cursor - timedelta(minutes=15))
        job = partial(history.get_significant_states, hass, begin, cursor,
                      entity_ids=active, include_start_time_state=False,
                      significant_changes_only=True, minimal_response=True, no_attributes=True)
        try:
            chunk = await asyncio.wait_for(recorder.get_instance(hass).async_add_executor_job(job), remaining)
        except TimeoutError:
            break
        for key, values in chunk.items():
            if key not in counts or key not in active:
                continue
            available = quota - counts[key]
            selected = values[-available:] if available else []
            data.setdefault(key, [])[:0] = plain(selected)
            counts[key] += len(selected)
            if len(values) > available or (counts[key] == quota and begin > earliest):
                limited.add(key)
        cursor = begin
        covered = (end - cursor).total_seconds() / (hours * 3600)
        rows = sum(counts.values())
        report("Verlauf lesen", 23 + 6 * max(covered, rows / row_limit), rows, unit="Verlaufzeilen")
    incomplete = cursor > earliest or bool(limited)
    return {"angefordert_von_utc": earliest.isoformat(), "bis_utc": end.isoformat(),
            "erfasst_ab_utc": cursor.isoformat(), "status": "teilweise" if incomplete else "erfolgreich",
            "hinweis": "Neueste Zustandsänderungen je Entität, ohne Attribute; gleichmässiges Zeilenbudget. Das Abfragezeitfenster ist keine Garantie für lückenlose Entitätsverläufe.",
            "zeilenlimit": row_limit, "zeilenlimit_je_entitaet": quota,
            "gekürzte_entitaeten": sorted(limited),
            "zeilen_je_entitaet": counts, "states": data}, incomplete


async def collect(hass, progress=None):
    started = utcnow()
    report = ProgressReporter(progress)
    report("HA-Zustände lesen", 2)
    files, issues, notes = {}, [], []
    result = {"started": started, "files": files, "issues": issues, "notes": notes, "local_references": []}

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
                                         "hinweis": "input_text-Inhalte absichtlich maskiert; last_reported ist kein externer Quellenzeitstempel",
                                         "eigenexport_hinweis": "Der eigene Exportstatus wurde während dieses Laufs aufgenommen und kann laeuft/0 Prozent sowie das vorherige ZIP zeigen. Der Abschluss dieses Archivs steht in manifest.json und EXPORTBERICHT.md."}
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

    # These are the same read-only entity properties used by HA's config and
    # reference queries (Core 2026.10); no automation/script is executed.
    for domain in ("automation", "script"):
        definitions = []
        component = hass.data.get(domain)
        if component is None:
            if any(s.entity_id.startswith(domain + ".") for s in states):
                problem("Definitionen " + domain, LookupError())
        else:
            try:
                for entity in component.entities:
                    try:
                        definitions.append({"entity_id": entity.entity_id,
                            "config": plain(entity.raw_config),
                            "referenzierte_entitaeten": sorted(entity.referenced_entities)})
                    except Exception as error:
                        problem("Definition " + str(entity.entity_id), error)
            except Exception as error:
                problem("Definitionen " + domain, error)
        files["runtime/definitionen_" + domain + ".json"] = definitions

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
    # Same bounded warning/error buffer exposed by HA's system_log/list. No
    # service call, no log clearing, and no claim to have the full Core log.
    try:
        records = hass.data["system_log"].records.to_list()
        files["diagnose/system_log.json"] = {
            "erfasst_utc": utcnow(), "entries": plain(records[:100]),
            "weitere_nicht_erfasst": max(0, len(records) - 100),
            "hinweis": "Begrenzter HA-Fehlerspeicher: Warnungen und Fehler seit Start, gegebenenfalls zusammengefasst; kein vollständiges Core-/Supervisor-Log"}
        if len(records) > 100:
            issues.append({"bereich": "HA-Fehlerspeicher", "status": "teilweise", "grund": "Limit 100 zusammengefasste Fehlereinträge erreicht"})
    except Exception as error:
        problem("HA-Fehlerspeicher", error)

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
            automatic = False
            try:
                files[filename] = plain(await asyncio.wait_for(dashboard.async_load(False), 45))
            except Exception as error:
                try:
                    const = importlib.import_module("homeassistant.components.lovelace.const")
                    if not isinstance(error, const.ConfigNotFound) or getattr(hass.config, "recovery_mode", False):
                        raise error
                    info = await asyncio.wait_for(dashboard.async_get_info(), 45)
                    if not isinstance(info, dict) or info.get("mode") != "auto-gen":
                        raise error
                    automatic = True
                    files[filename] = {"status": "automatisch_generiert", "info": plain(info),
                        "hinweis": "HA hat keine gespeicherte Kartenkonfiguration; diese Übersicht wird im Frontend generiert. Laufzeitdaten und Registries sind enthalten, das erzeugte Layout ist nicht als statische Kartenliste erfasst."}
                except Exception:
                    problem(filename, error)
            dashboard_rows.append({"url_path": key, "archivpfad": filename,
                                   "manager_type": type(dashboard).__name__, "geladen": filename in files and not automatic,
                                   "status": "automatisch_generiert" if automatic else "erfasst" if filename in files else "fehlgeschlagen",
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
        if name.startswith(("dashboards/", "inventar/integrationen", "runtime/definitionen_")):
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
    selection_info = select_history(states, files)
    files["diagnose/verlauf_auswahl.json"] = selection_info
    selection = selection_info["entity_ids"]
    if selection_info["weitere_nicht_erfasst"]:
        issues.append({"bereich": "Verlaufsauswahl", "status": "teilweise", "grund": "Limit 100 Entitäten erreicht; weitere Referenzen stehen in diagnose/verlauf_auswahl.json"})
    if selection:
        report("Verlauf lesen", 23, 0, unit="Verlaufzeilen")
        try:
            history_data, incomplete = await history_snapshot(hass, selection, report)
            if incomplete:
                issues.append({"bereich": "Verlauf", "status": "teilweise", "grund": "Verlauf wegen Zeilenbudget je Entität oder 40-Sekunden-Limit teilweise erfasst; Grenzen und Zähler stehen in diagnose/verlauf.json"})
            files["diagnose/verlauf.json"] = history_data
        except Exception as error:
            problem("Verlauf", error)

    # Diagnostics contain integration-specific privacy-sensitive information. Record support,
    # but do not blindly call every custom provider in a generic audit exporter.
    files["diagnose/umfang.json"] = {
        "integration_diagnosen": "nicht automatisch abgerufen; Anbieterformat/Maskierung muss je Integration geprüft werden",
        "statistikdaten": "nicht automatisch abgerufen; bei Statistik-/Energiekarten gezielt ergänzen",
        "traces": "Vorhandene .storage/trace.saved_traces wird maskiert vom Datenträger mitgesammelt; keine aktuellen Laufzeittraces abgefragt und keine neue Trace-Ausführung",
        "externe_apps": "Nur unter /config vorhandene Quellen; keine Supervisor-/App-/Controller-Konfiguration ausserhalb dieses Bereichs",
        "system_logs": "HA-Fehlerspeicher bis 100 zusammengefasste Einträge; vorhandene lokale HA-Logdateien jeweils letzte 256 KiB; kein vollständiges Core-/Supervisor-Log",
        "quellen_cache": "Vorhandene JSON-/Textquellen unter /config; keine beliebigen unbekannten Dienste"}
    notes.append({"bereich": "Ergänzende Diagnosen/Statistiken/externe Apps", "status": "hinweis",
                   "grund": "Keine pauschale Erfassung; Bedarf anhand Dashboard und Integrationen im Gesamtprüfauftrag klären"})
    files["runtime/snapshot_zeitfenster.json"] = {"start_utc": started, "ende_utc": utcnow(), "atomar": False}
    report("HA-Daten gelesen", 30)
    return result
