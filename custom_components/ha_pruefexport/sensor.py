"""One status entity, no fabricated measurement values."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, SENSOR_ID, STATES, VERSION


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ExportStatus(entry.runtime_data)])


class ExportStatus(SensorEntity):
    _attr_name = "HA Prüfexport"
    _attr_unique_id = DOMAIN + "_status"
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATES
    _attr_icon = "mdi:archive-arrow-down-outline"

    def __init__(self, manager):
        self.manager = manager
        self.entity_id = SENSOR_ID
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, DOMAIN)}, name="HA Prüfexport", manufacturer="Lokaler Prüfexport", sw_version=VERSION)

    @property
    def native_value(self):
        return self.manager.status["state"]

    @property
    def extra_state_attributes(self):
        return self.manager.attributes()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.subscribe(self.async_write_ha_state))
