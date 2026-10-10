"""Installable local audit export integration."""
import voluptuous as vol

from aiohttp import web

from homeassistant.components.http import KEY_HASS, KEY_HASS_USER, HomeAssistantView
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN, DOWNLOAD_PREFIX
from .manager import ExportManager


EXPORT_SCHEMA = vol.Schema(
    # Accept the old card parameter without exposing a choice of audit scopes.
    {vol.Optional("pruefmodus"): vol.In(("methode", "gesamt"))},
    extra=vol.PREVENT_EXTRA,
)


class DownloadView(HomeAssistantView):
    url = DOWNLOAD_PREFIX + "{filename}"
    name = "api:ha_pruefexport:download"
    requires_auth = True

    async def get(self, request, filename):
        user = request.get(KEY_HASS_USER)
        if user is None or not user.is_admin:
            raise web.HTTPForbidden()
        hass = request.app[KEY_HASS]
        manager = hass.data.get(DOMAIN)
        if manager is None:
            raise web.HTTPNotFound()
        path = await hass.async_add_executor_job(manager.archive_path, filename)
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Content-Type": "application/zip",
                   "Content-Disposition": 'attachment; filename="' + path.name + '"',
                   "Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"})


async def async_setup(hass, config):
    hass.http.register_view(DownloadView())

    async def export(call):
        manager = hass.data.get(DOMAIN)
        if manager is None:
            raise HomeAssistantError("Bitte zuerst die Integration HA Prüfexport einrichten")
        manager.start()
    async_register_admin_service(hass, DOMAIN, "export", export, schema=EXPORT_SCHEMA)
    return True


async def async_setup_entry(hass, entry):
    manager = ExportManager(hass)
    await manager.async_load()
    hass.data[DOMAIN] = manager
    entry.runtime_data = manager
    async def stop(event):
        await manager.async_stop()
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        await entry.runtime_data.async_stop()
        hass.data.pop(DOMAIN, None)
        return True
    return False
