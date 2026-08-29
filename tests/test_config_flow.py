"""Tests for the Claude Usage configuration flow."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant import loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.config_entries import ConfigEntries, SOURCE_REAUTH, SOURCE_USER
from homeassistant.core import HomeAssistant

from custom_components.hass_claude_usage import config_flow
from custom_components.hass_claude_usage.api import ClaudeAccountInfo
from custom_components.hass_claude_usage.binary_sensor import ClaudeUsageBinarySensor
from custom_components.hass_claude_usage.const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_NAME,
    CONF_ACCOUNT_UUID,
    CONF_EXPIRES_AT,
    CONF_ORGANIZATION_NAME,
    CONF_ORGANIZATION_TYPE,
    CONF_ORGANIZATION_UUID,
    CONF_REFRESH_TOKEN,
    CONF_SUBSCRIPTION_LEVEL,
    DOMAIN,
)
from custom_components.hass_claude_usage.sensor import ClaudeUsageSensor


class _UsageResponse:
    """Minimal successful response for the integration's usage request."""

    status = 200

    def raise_for_status(self) -> None:
        """Accept the response."""

    async def json(self) -> dict[str, Any]:
        """Return an empty usage payload."""
        return {}


class _UsageSession:
    """Keep entry setup local by serving the usage request."""

    async def get(self, *args: object, **kwargs: object) -> _UsageResponse:
        """Return the usage response."""
        return _UsageResponse()


async def _async_hass(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> HomeAssistant:
    """Create Home Assistant with its real config entry flow manager."""
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    await loader.async_get_custom_components(hass)
    await async_load_base_functionality(hass)
    hass.data[loader.DATA_COMPONENTS][f"{DOMAIN}.config_flow"] = config_flow

    from custom_components.hass_claude_usage import aiohttp_client

    monkeypatch.setattr(aiohttp_client, "async_get_clientsession", lambda hass: _UsageSession())
    return hass


def _token_data(access_token: str = "new-access-token") -> dict[str, Any]:
    return {
        "access_token": access_token,
        "refresh_token": "new-refresh-token",
        "expires_in": 3600,
    }


async def _async_configure_user(
    hass: HomeAssistant,
    auth_code: str,
) -> dict[str, Any]:
    """Run the real user flow through Home Assistant's flow manager."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"auth_code": auth_code}
    )


def test_user_flows_scope_entries_by_account_and_organization(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create entries for two organizations and abort a duplicate pair."""

    async def run() -> None:
        hass = await _async_hass(tmp_path, monkeypatch)
        monkeypatch.setattr(
            config_flow.ClaudeUsageConfigFlow,
            "_exchange_code",
            AsyncMock(
                side_effect=[_token_data("token-a"), _token_data("token-b"), _token_data("token-a")]
            ),
        )
        monkeypatch.setattr(
            config_flow,
            "async_fetch_account_info",
            AsyncMock(
                side_effect=[
                    ClaudeAccountInfo(
                        "account-a",
                        "Alice",
                        "personal-org",
                        "Alice Personal",
                        "claude_max",
                        "Max",
                    ),
                    ClaudeAccountInfo(
                        "account-a",
                        "Alice",
                        "team-org",
                        "Example Team",
                        "claude_team",
                        "Team",
                    ),
                    ClaudeAccountInfo(
                        "account-a",
                        "Alice",
                        "team-org",
                        "Example Team",
                        "claude_team",
                        "Team",
                    ),
                ]
            ),
        )

        first = await _async_configure_user(hass, "first-code")
        second = await _async_configure_user(hass, "second-code")
        duplicate = await _async_configure_user(hass, "duplicate-code")

        first_entry = first["result"]
        second_entry = second["result"]
        assert first_entry.version == 3
        assert second_entry.version == 3
        assert first_entry.unique_id == "account-a:personal-org"
        assert second_entry.unique_id == "account-a:team-org"
        assert first_entry.data[CONF_ACCOUNT_UUID] == "account-a"
        assert second_entry.data[CONF_ACCOUNT_UUID] == "account-a"
        assert first_entry.data[CONF_ORGANIZATION_UUID] == "personal-org"
        assert first_entry.data[CONF_ORGANIZATION_NAME] == "Alice Personal"
        assert first_entry.data[CONF_ORGANIZATION_TYPE] == "claude_max"
        assert second_entry.data[CONF_ORGANIZATION_UUID] == "team-org"
        assert second_entry.data[CONF_ORGANIZATION_NAME] == "Example Team"
        assert second_entry.data[CONF_ORGANIZATION_TYPE] == "claude_team"
        assert first_entry.title != second_entry.title
        assert "Alice Personal" in first_entry.title
        assert "Example Team" in second_entry.title
        assert duplicate["type"] == "abort"
        assert duplicate["reason"] == "already_configured"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 2

    asyncio.run(run())


def test_user_flow_requires_profile_before_creating_entry(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep setup on the form when the authenticated profile cannot be verified."""

    async def run() -> None:
        hass = await _async_hass(tmp_path, monkeypatch)
        monkeypatch.setattr(
            config_flow.ClaudeUsageConfigFlow,
            "_exchange_code",
            AsyncMock(return_value=_token_data()),
        )
        monkeypatch.setattr(
            config_flow,
            "async_fetch_account_info",
            AsyncMock(return_value=None),
        )

        result = await _async_configure_user(hass, "code")

        assert result["type"] == "form"
        assert result["errors"] == {"base": "profile_failed"}
        assert hass.config_entries.async_entries(DOMAIN) == []

    asyncio.run(run())


def test_platform_device_names_include_organization(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Include stored organization context in both platform device names."""

    async def run() -> None:
        hass = await _async_hass(tmp_path, monkeypatch)
        entry = await _async_create_entry_for_reauth(hass, monkeypatch)
        await hass.async_block_till_done()

        sensor = ClaudeUsageSensor(
            entry.runtime_data,
            entry,
            "test_sensor",
            "Test Sensor",
            None,
            "mdi:test-tube",
            None,
        )
        binary_sensor = ClaudeUsageBinarySensor(
            entry.runtime_data,
            entry,
            "test_binary_sensor",
            "Test Binary Sensor",
            "mdi:test-tube",
            "problem",
        )

        assert "Alice Personal" in sensor.device_info["name"]
        assert "Alice Personal" in binary_sensor.device_info["name"]

    asyncio.run(run())


def test_organization_uuid_is_display_fallback(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the required organization UUID when its optional name is absent."""

    async def run() -> None:
        hass = await _async_hass(tmp_path, monkeypatch)
        monkeypatch.setattr(
            config_flow.ClaudeUsageConfigFlow,
            "_exchange_code",
            AsyncMock(return_value=_token_data()),
        )
        monkeypatch.setattr(
            config_flow,
            "async_fetch_account_info",
            AsyncMock(
                return_value=ClaudeAccountInfo(
                    "account-a",
                    "Alice",
                    "personal-org",
                    None,
                    "claude_max",
                    "Max",
                )
            ),
        )

        result = await _async_configure_user(hass, "code")
        entry = result["result"]
        await hass.async_block_till_done()
        sensor = ClaudeUsageSensor(
            entry.runtime_data,
            entry,
            "test_sensor",
            "Test Sensor",
            None,
            "mdi:test-tube",
            None,
        )
        binary_sensor = ClaudeUsageBinarySensor(
            entry.runtime_data,
            entry,
            "test_binary_sensor",
            "Test Binary Sensor",
            "mdi:test-tube",
            "problem",
        )

        assert "personal-org" in entry.title
        assert "personal-org" in sensor.device_info["name"]
        assert "personal-org" in binary_sensor.device_info["name"]

    asyncio.run(run())


async def _async_create_entry_for_reauth(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Create the existing config entry through the real user flow."""
    monkeypatch.setattr(
        config_flow.ClaudeUsageConfigFlow,
        "_exchange_code",
        AsyncMock(return_value=_token_data("old-access-token")),
    )
    monkeypatch.setattr(
        config_flow,
        "async_fetch_account_info",
        AsyncMock(
            return_value=ClaudeAccountInfo(
                "account-a",
                "Alice",
                "personal-org",
                "Alice Personal",
                "claude_max",
                "Max",
            )
        ),
    )
    result = await _async_configure_user(hass, "initial-code")
    return result["result"]


async def _async_configure_reauth(
    hass: HomeAssistant,
    entry_id: str,
) -> dict[str, Any]:
    """Run the real reauthentication flow through Home Assistant's manager."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry_id},
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"auth_code": "code"})


def test_reauth_updates_matching_entry_after_profile_validation(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Update a real entry when its reauthenticated composite identity matches."""

    async def run() -> None:
        hass = await _async_hass(tmp_path, monkeypatch)
        entry = await _async_create_entry_for_reauth(hass, monkeypatch)
        monkeypatch.setattr(
            config_flow.ClaudeUsageConfigFlow,
            "_exchange_code",
            AsyncMock(return_value=_token_data("refreshed-access-token")),
        )
        monkeypatch.setattr(
            config_flow,
            "async_fetch_account_info",
            AsyncMock(
                return_value=ClaudeAccountInfo(
                    "account-a",
                    "Alice New",
                    "personal-org",
                    "Alice Personal Updated",
                    "claude_pro",
                    "Pro",
                )
            ),
        )

        result = await _async_configure_reauth(hass, entry.entry_id)

        assert result["type"] == "abort"
        assert result["reason"] == "reauth_successful"
        assert entry.unique_id == "account-a:personal-org"
        assert entry.data[CONF_ACCESS_TOKEN] == "refreshed-access-token"
        assert entry.data[CONF_REFRESH_TOKEN] == "new-refresh-token"
        assert CONF_EXPIRES_AT in entry.data
        assert entry.data[CONF_ACCOUNT_UUID] == "account-a"
        assert entry.data[CONF_ACCOUNT_NAME] == "Alice New"
        assert entry.data[CONF_ORGANIZATION_UUID] == "personal-org"
        assert entry.data[CONF_ORGANIZATION_NAME] == "Alice Personal Updated"
        assert entry.data[CONF_ORGANIZATION_TYPE] == "claude_pro"
        assert entry.data[CONF_SUBSCRIPTION_LEVEL] == "Pro"

    asyncio.run(run())


def test_reauth_rejects_mismatched_profile_without_updating_entry(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep an entry unchanged when reauth selects another organization."""

    async def run() -> None:
        hass = await _async_hass(tmp_path, monkeypatch)
        entry = await _async_create_entry_for_reauth(hass, monkeypatch)
        original_data = entry.data
        monkeypatch.setattr(
            config_flow.ClaudeUsageConfigFlow,
            "_exchange_code",
            AsyncMock(return_value=_token_data("wrong-access-token")),
        )
        monkeypatch.setattr(
            config_flow,
            "async_fetch_account_info",
            AsyncMock(
                return_value=ClaudeAccountInfo(
                    "account-a",
                    "Alice",
                    "team-org",
                    "Example Team",
                    "claude_team",
                    "Team",
                )
            ),
        )

        result = await _async_configure_reauth(hass, entry.entry_id)

        assert result["type"] == "abort"
        assert result["reason"] == "wrong_account"
        assert entry.unique_id == "account-a:personal-org"
        assert entry.data == original_data

    asyncio.run(run())


def test_reauth_migrates_legacy_entry_to_composite_identity(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adopt the profile's composite identity when reauthenticating a pre-v3 entry."""

    async def run() -> None:
        hass = await _async_hass(tmp_path, monkeypatch)
        entry = await _async_create_entry_for_reauth(hass, monkeypatch)

        # Simulate a pre-v3 entry: version 2 with an account-only unique_id.
        hass.config_entries.async_update_entry(entry, version=2, unique_id="account-a")
        assert entry.version == 2
        assert entry.unique_id == "account-a"

        monkeypatch.setattr(
            config_flow.ClaudeUsageConfigFlow,
            "_exchange_code",
            AsyncMock(return_value=_token_data("migrated-access-token")),
        )
        monkeypatch.setattr(
            config_flow,
            "async_fetch_account_info",
            AsyncMock(
                return_value=ClaudeAccountInfo(
                    "account-a",
                    "Alice",
                    "personal-org",
                    "Alice Personal",
                    "claude_max",
                    "Max",
                )
            ),
        )

        result = await _async_configure_reauth(hass, entry.entry_id)

        assert result["type"] == "abort"
        assert result["reason"] == "reauth_successful"
        assert entry.unique_id == "account-a:personal-org"
        assert entry.version == 3
        assert entry.data[CONF_ACCESS_TOKEN] == "migrated-access-token"
        assert entry.data[CONF_ACCOUNT_UUID] == "account-a"
        assert entry.data[CONF_ORGANIZATION_UUID] == "personal-org"

    asyncio.run(run())


def test_reauth_legacy_entry_collision_aborts_already_configured_without_mutation(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse to steal an identity another entry already owns during legacy reauth."""

    async def run() -> None:
        hass = await _async_hass(tmp_path, monkeypatch)

        # Owner already holds the account-a:personal-org composite identity.
        await _async_create_entry_for_reauth(hass, monkeypatch)

        # A second, distinct entry for a different organization.
        monkeypatch.setattr(
            config_flow.ClaudeUsageConfigFlow,
            "_exchange_code",
            AsyncMock(return_value=_token_data("legacy-access-token")),
        )
        monkeypatch.setattr(
            config_flow,
            "async_fetch_account_info",
            AsyncMock(
                return_value=ClaudeAccountInfo(
                    "account-a", "Alice", "team-org", "Example Team", "claude_team", "Team"
                )
            ),
        )
        legacy_result = await _async_configure_user(hass, "legacy-code")
        legacy_entry = legacy_result["result"]

        # Simulate a pre-v3 entry whose stored identity predates the composite.
        hass.config_entries.async_update_entry(legacy_entry, version=2, unique_id="account-a")
        original_version = legacy_entry.version
        original_unique_id = legacy_entry.unique_id
        original_data = dict(legacy_entry.data)

        # Reauth now resolves to the identity the owner entry already holds.
        monkeypatch.setattr(
            config_flow.ClaudeUsageConfigFlow,
            "_exchange_code",
            AsyncMock(return_value=_token_data("collide-access-token")),
        )
        monkeypatch.setattr(
            config_flow,
            "async_fetch_account_info",
            AsyncMock(
                return_value=ClaudeAccountInfo(
                    "account-a",
                    "Alice",
                    "personal-org",
                    "Alice Personal",
                    "claude_max",
                    "Max",
                )
            ),
        )

        result = await _async_configure_reauth(hass, legacy_entry.entry_id)

        assert result["type"] == "abort"
        assert result["reason"] == "already_configured"
        assert legacy_entry.version == original_version
        assert legacy_entry.unique_id == original_unique_id
        assert dict(legacy_entry.data) == original_data

    asyncio.run(run())


def test_reauth_requires_profile_before_updating_entry(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep credentials unchanged when the reauthentication profile is unavailable."""

    async def run() -> None:
        hass = await _async_hass(tmp_path, monkeypatch)
        entry = await _async_create_entry_for_reauth(hass, monkeypatch)
        original_data = entry.data
        monkeypatch.setattr(
            config_flow.ClaudeUsageConfigFlow,
            "_exchange_code",
            AsyncMock(return_value=_token_data("unverified-access-token")),
        )
        monkeypatch.setattr(config_flow, "async_fetch_account_info", AsyncMock(return_value=None))

        result = await _async_configure_reauth(hass, entry.entry_id)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "profile_failed"}
        assert entry.data == original_data

    asyncio.run(run())
