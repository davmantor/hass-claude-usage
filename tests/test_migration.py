"""Tests for config entry migration."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components import hass_claude_usage as integration
from custom_components.hass_claude_usage.api import ClaudeAccountInfo
from custom_components.hass_claude_usage.const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_NAME,
    CONF_ACCOUNT_UUID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_SUBSCRIPTION_LEVEL,
    DOMAIN,
)


def test_migrates_legacy_entry_to_account_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Migrate a legacy entry only after credentials and identity are available."""

    async def run() -> None:
        original_data = {
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_REFRESH_TOKEN: "old-refresh-token",
            CONF_EXPIRES_AT: 0,
            "unrelated": "preserved",
        }
        valid_data = {
            **original_data,
            CONF_ACCESS_TOKEN: "new-access-token",
            CONF_REFRESH_TOKEN: "new-refresh-token",
            CONF_EXPIRES_AT: 1234567890,
        }
        options = {"update_interval": 900, "unrelated_option": True}
        entry = SimpleNamespace(
            version=1,
            unique_id=DOMAIN,
            data=original_data,
            options=options,
        )
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )
        monkeypatch.setattr(
            integration,
            "_async_get_valid_entry_data",
            AsyncMock(return_value=valid_data),
            raising=False,
        )
        monkeypatch.setattr(
            integration,
            "async_fetch_account_info",
            AsyncMock(return_value=ClaudeAccountInfo("account-a", "Alice", "Max")),
            raising=False,
        )

        assert await integration.async_migrate_entry(hass, entry) is True

        update_entry.assert_called_once_with(
            entry,
            data={
                **valid_data,
                CONF_ACCOUNT_UUID: "account-a",
                CONF_ACCOUNT_NAME: "Alice",
                CONF_SUBSCRIPTION_LEVEL: "Max",
            },
            unique_id="account-a",
            version=2,
        )
        assert entry.options == options

    asyncio.run(run())


@pytest.mark.parametrize(
    "error",
    [ConfigEntryAuthFailed("invalid token"), UpdateFailed("refresh unavailable")],
)
def test_token_validation_failure_leaves_legacy_entry_untouched(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    """Abort migration without a write when credentials cannot be validated."""

    async def run() -> None:
        original_data = {
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_REFRESH_TOKEN: "old-refresh-token",
            "unrelated": "preserved",
        }
        options = {"update_interval": 900}
        entry = SimpleNamespace(version=1, unique_id=DOMAIN, data=original_data, options=options)
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )
        get_valid_data = AsyncMock(side_effect=error)
        fetch_account_info = AsyncMock()
        monkeypatch.setattr(integration, "_async_get_valid_entry_data", get_valid_data)
        monkeypatch.setattr(integration, "async_fetch_account_info", fetch_account_info)

        assert await integration.async_migrate_entry(hass, entry) is False

        fetch_account_info.assert_not_awaited()
        update_entry.assert_not_called()
        assert entry.data == original_data
        assert entry.options == options

    asyncio.run(run())


def test_profile_identity_failure_leaves_legacy_entry_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Abort migration without committing refreshed data when identity is missing."""

    async def run() -> None:
        original_data = {
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_REFRESH_TOKEN: "old-refresh-token",
            CONF_EXPIRES_AT: 0,
            "unrelated": "preserved",
        }
        valid_data = {
            **original_data,
            CONF_ACCESS_TOKEN: "new-access-token",
            CONF_EXPIRES_AT: 1234567890,
        }
        options = {"update_interval": 900}
        entry = SimpleNamespace(version=1, unique_id=DOMAIN, data=original_data, options=options)
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )
        monkeypatch.setattr(
            integration,
            "_async_get_valid_entry_data",
            AsyncMock(return_value=valid_data),
        )
        monkeypatch.setattr(
            integration,
            "async_fetch_account_info",
            AsyncMock(return_value=None),
        )

        assert await integration.async_migrate_entry(hass, entry) is False

        update_entry.assert_not_called()
        assert entry.data == original_data
        assert entry.options == options

    asyncio.run(run())


def test_version_two_entry_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return immediately for an entry already at the current version."""

    async def run() -> None:
        data = {
            CONF_ACCESS_TOKEN: "access-token",
            CONF_ACCOUNT_UUID: "account-a",
        }
        options = {"update_interval": 900}
        entry = SimpleNamespace(version=2, unique_id="account-a", data=data, options=options)
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )
        get_valid_data = AsyncMock(return_value=data)
        fetch_account_info = AsyncMock(
            return_value=ClaudeAccountInfo("account-a", "Alice", "Max")
        )
        monkeypatch.setattr(integration, "_async_get_valid_entry_data", get_valid_data)
        monkeypatch.setattr(integration, "async_fetch_account_info", fetch_account_info)

        assert await integration.async_migrate_entry(hass, entry) is True

        get_valid_data.assert_not_awaited()
        fetch_account_info.assert_not_awaited()
        update_entry.assert_not_called()
        assert entry.data == data
        assert entry.options == options

    asyncio.run(run())
