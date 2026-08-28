"""Binary sensor platform for Claude Usage integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ClaudeUsageConfigEntry, ClaudeUsageCoordinator
from .const import (
    BINARY_SENSOR_DEFINITIONS,
    CONF_ACCOUNT_NAME,
    CONF_ORGANIZATION_NAME,
    CONF_ORGANIZATION_UUID,
    CONF_SUBSCRIPTION_LEVEL,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClaudeUsageConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Claude Usage binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        ClaudeUsageBinarySensor(coordinator, entry, key, name, icon, device_class)
        for key, name, icon, device_class in BINARY_SENSOR_DEFINITIONS
    )


class ClaudeUsageBinarySensor(CoordinatorEntity[ClaudeUsageCoordinator], BinarySensorEntity):
    """A binary sensor for a Claude usage diagnostic state."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ClaudeUsageCoordinator,
        entry: ClaudeUsageConfigEntry,
        key: str,
        name: str,
        icon: str,
        device_class: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_name = name
        self._attr_icon = icon
        if device_class == "problem":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM

        account_name = entry.data.get(CONF_ACCOUNT_NAME)
        organization_name = entry.data.get(CONF_ORGANIZATION_NAME) or entry.data.get(
            CONF_ORGANIZATION_UUID
        )
        subscription_level = entry.data.get(CONF_SUBSCRIPTION_LEVEL)

        device_name_details = list(
            dict.fromkeys(filter(None, (account_name, organization_name, subscription_level)))
        )
        device_name = "Claude Usage"
        if device_name_details:
            device_name += f" ({' - '.join(device_name_details)})"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=device_name,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Return True because this diagnostic reflects coordinator status."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True when the coordinator is reporting an API error."""
        return not self.coordinator.last_update_success
