"""Tests for config entry migration."""

import asyncio
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntries, ConfigEntry, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components import hass_claude_usage as integration
from custom_components.hass_claude_usage.api import ClaudeAccountInfo, account_organization_id
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

ACCOUNT_ORG_INFO = ClaudeAccountInfo(
    account_uuid="account-a",
    account_name="Alice",
    organization_uuid="team-org",
    organization_name="Team Org",
    organization_type="claude_team",
    subscription_level="Team",
)
ACCOUNT_ORG_ID = account_organization_id(ACCOUNT_ORG_INFO)


def _registered_entry(
    hass: HomeAssistant,
    *,
    unique_id: str,
    version: int,
    data: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> ConfigEntry:
    """Register a real config entry in Home Assistant's entry registry."""
    entry = ConfigEntry(
        data=data,
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options=options or {},
        source=SOURCE_USER,
        title="Claude Usage",
        unique_id=unique_id,
        version=version,
    )
    hass.config_entries._entries[entry.entry_id] = entry
    return entry


@pytest.mark.parametrize("legacy_version", [1, 2])
def test_real_registered_entry_migrates_and_reindexes(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    legacy_version: int,
) -> None:
    """Atomically migrate and reindex a registered legacy entry to organization scope."""

    async def run() -> None:
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = ConfigEntries(hass, {})
        original_data = {
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_REFRESH_TOKEN: "old-refresh-token",
            "unrelated": "preserved",
        }
        valid_data = {
            **original_data,
            CONF_ACCESS_TOKEN: "new-access-token",
            CONF_EXPIRES_AT: 1234567890,
        }
        options = {"update_interval": 900, "unrelated_option": True}
        entry = _registered_entry(
            hass,
            unique_id=DOMAIN,
            version=legacy_version,
            data=original_data,
            options=options,
        )
        monkeypatch.setattr(
            integration,
            "_async_get_valid_entry_data",
            AsyncMock(return_value=valid_data),
        )
        monkeypatch.setattr(
            integration,
            "async_fetch_account_info",
            AsyncMock(return_value=ACCOUNT_ORG_INFO),
        )

        assert await integration.async_migrate_entry(hass, entry) is True

        assert entry.version == 3
        assert entry.unique_id == ACCOUNT_ORG_ID
        assert entry.title == "Claude Usage (Alice - Team Org - Team)"
        assert dict(entry.data) == {
            **valid_data,
            CONF_ACCOUNT_UUID: "account-a",
            CONF_ACCOUNT_NAME: "Alice",
            CONF_ORGANIZATION_UUID: "team-org",
            CONF_ORGANIZATION_NAME: "Team Org",
            CONF_ORGANIZATION_TYPE: "claude_team",
            CONF_SUBSCRIPTION_LEVEL: "Team",
        }
        assert dict(entry.options) == options
        assert hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, DOMAIN) is None
        assert hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, ACCOUNT_ORG_ID) is entry

    asyncio.run(run())


def test_real_registered_entry_collision_does_not_mutate(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject migration when another registered entry owns the composite identity."""

    async def run() -> None:
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = ConfigEntries(hass, {})
        owner = _registered_entry(
            hass,
            unique_id=ACCOUNT_ORG_ID,
            version=3,
            data={CONF_ACCESS_TOKEN: "owner-token", CONF_ACCOUNT_UUID: "account-a"},
        )
        original_data = {
            CONF_ACCESS_TOKEN: "legacy-token",
            CONF_REFRESH_TOKEN: "legacy-refresh-token",
            "unrelated": "preserved",
        }
        options = {"update_interval": 900}
        legacy = _registered_entry(
            hass,
            unique_id=DOMAIN,
            version=1,
            data=original_data,
            options=options,
        )
        update_entry = MagicMock(wraps=hass.config_entries.async_update_entry)
        monkeypatch.setattr(hass.config_entries, "async_update_entry", update_entry)
        monkeypatch.setattr(
            integration,
            "_async_get_valid_entry_data",
            AsyncMock(return_value={**original_data, CONF_ACCESS_TOKEN: "refreshed-token"}),
        )
        monkeypatch.setattr(
            integration,
            "async_fetch_account_info",
            AsyncMock(return_value=ACCOUNT_ORG_INFO),
        )

        assert await integration.async_migrate_entry(hass, legacy) is False

        assert legacy.version == 1
        assert legacy.unique_id == DOMAIN
        assert dict(legacy.data) == original_data
        assert dict(legacy.options) == options
        update_entry.assert_not_called()
        assert hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, DOMAIN) is legacy
        assert hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, ACCOUNT_ORG_ID) is owner

    asyncio.run(run())


def test_real_registered_entry_different_organization_does_not_collide(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow migration when the same account already has a differently scoped entry."""

    async def run() -> None:
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = ConfigEntries(hass, {})
        other_org_id = "account-a:other-org"
        other_org_entry = _registered_entry(
            hass,
            unique_id=other_org_id,
            version=3,
            data={CONF_ACCESS_TOKEN: "other-token", CONF_ACCOUNT_UUID: "account-a"},
        )
        original_data = {
            CONF_ACCESS_TOKEN: "legacy-token",
            CONF_REFRESH_TOKEN: "legacy-refresh-token",
        }
        entry = _registered_entry(
            hass,
            unique_id=DOMAIN,
            version=1,
            data=original_data,
        )
        monkeypatch.setattr(
            integration,
            "_async_get_valid_entry_data",
            AsyncMock(return_value=original_data),
        )
        monkeypatch.setattr(
            integration,
            "async_fetch_account_info",
            AsyncMock(return_value=ACCOUNT_ORG_INFO),
        )

        assert await integration.async_migrate_entry(hass, entry) is True

        assert entry.version == 3
        assert entry.unique_id == ACCOUNT_ORG_ID
        assert (
            hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, other_org_id)
            is other_org_entry
        )
        assert hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, ACCOUNT_ORG_ID) is entry

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


def test_version_three_entry_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return immediately for an entry already at the current version."""

    async def run() -> None:
        data = {
            CONF_ACCESS_TOKEN: "access-token",
            CONF_ACCOUNT_UUID: "account-a",
            CONF_ORGANIZATION_UUID: "team-org",
        }
        options = {"update_interval": 900}
        entry = SimpleNamespace(version=3, unique_id=ACCOUNT_ORG_ID, data=data, options=options)
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )
        get_valid_data = AsyncMock(return_value=data)
        fetch_account_info = AsyncMock(return_value=ACCOUNT_ORG_INFO)
        monkeypatch.setattr(integration, "_async_get_valid_entry_data", get_valid_data)
        monkeypatch.setattr(integration, "async_fetch_account_info", fetch_account_info)

        assert await integration.async_migrate_entry(hass, entry) is True

        get_valid_data.assert_not_awaited()
        fetch_account_info.assert_not_awaited()
        update_entry.assert_not_called()
        assert entry.data == data
        assert entry.options == options

    asyncio.run(run())


def test_unsupported_version_is_rejected_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a future entry version without requests, writes, or downgrade."""

    async def run() -> None:
        data = {
            CONF_ACCESS_TOKEN: "access-token",
            CONF_ACCOUNT_UUID: "account-a",
        }
        options = {"update_interval": 900}
        entry = SimpleNamespace(version=4, unique_id=ACCOUNT_ORG_ID, data=data, options=options)
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )
        get_valid_data = AsyncMock(return_value=data)
        fetch_account_info = AsyncMock(return_value=ACCOUNT_ORG_INFO)
        monkeypatch.setattr(integration, "_async_get_valid_entry_data", get_valid_data)
        monkeypatch.setattr(integration, "async_fetch_account_info", fetch_account_info)

        assert await integration.async_migrate_entry(hass, entry) is False

        get_valid_data.assert_not_awaited()
        fetch_account_info.assert_not_awaited()
        update_entry.assert_not_called()
        assert entry.version == 4
        assert entry.data == data
        assert entry.options == options

    asyncio.run(run())


def test_token_refresh_returns_merged_copy_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return refreshed entry data without committing it."""

    async def run() -> None:
        original_data = {
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_REFRESH_TOKEN: "old-refresh-token",
            CONF_EXPIRES_AT: 0,
            "unrelated": "preserved",
        }
        entry = SimpleNamespace(data=original_data)
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )
        response = SimpleNamespace(
            ok=True,
            status=200,
            json=AsyncMock(
                return_value={
                    CONF_ACCESS_TOKEN: "new-access-token",
                    CONF_REFRESH_TOKEN: "new-refresh-token",
                    "expires_in": 3600,
                }
            ),
        )
        session = SimpleNamespace(post=AsyncMock(return_value=response))
        monkeypatch.setattr(
            integration.aiohttp_client,
            "async_get_clientsession",
            lambda hass: session,
        )
        monkeypatch.setattr(integration.time, "time", lambda: 1000)

        result = await integration._async_get_valid_entry_data(hass, entry)

        assert result == {
            CONF_ACCESS_TOKEN: "new-access-token",
            CONF_REFRESH_TOKEN: "new-refresh-token",
            CONF_EXPIRES_AT: 4600,
            "unrelated": "preserved",
        }
        assert result is not original_data
        assert entry.data == original_data
        update_entry.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "malformed_json", "non_mapping"])
def test_token_refresh_response_failures_are_update_failed(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Normalize transport and malformed refresh responses without writing."""

    async def run() -> None:
        original_data = {
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_REFRESH_TOKEN: "old-refresh-token",
            CONF_EXPIRES_AT: 0,
        }
        entry = SimpleNamespace(data=original_data)
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )

        if failure == "timeout":
            post = AsyncMock(side_effect=asyncio.TimeoutError)
        else:
            json = (
                AsyncMock(side_effect=ValueError("invalid JSON"))
                if failure == "malformed_json"
                else AsyncMock(return_value=[])
            )
            post = AsyncMock(return_value=SimpleNamespace(ok=True, status=200, json=json))
        session = SimpleNamespace(post=post)
        monkeypatch.setattr(
            integration.aiohttp_client,
            "async_get_clientsession",
            lambda hass: session,
        )

        with pytest.raises(UpdateFailed):
            await integration._async_get_valid_entry_data(hass, entry)

        assert entry.data == original_data
        update_entry.assert_not_called()

    asyncio.run(run())


def test_coordinator_commits_changed_valid_entry_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commit refreshed credentials during normal coordinator polling."""

    async def run() -> None:
        original_data = {CONF_ACCESS_TOKEN: "old-access-token"}
        refreshed_data = {CONF_ACCESS_TOKEN: "new-access-token"}
        entry = SimpleNamespace(data=original_data)
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )
        coordinator = SimpleNamespace(hass=hass, config_entry=entry)
        monkeypatch.setattr(
            integration,
            "_async_get_valid_entry_data",
            AsyncMock(return_value=refreshed_data),
        )

        await integration.ClaudeUsageCoordinator._ensure_valid_token(coordinator)

        update_entry.assert_called_once_with(entry, data=refreshed_data)

    asyncio.run(run())


def test_coordinator_does_not_commit_unchanged_valid_entry_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid a config-entry write when token data is already current."""

    async def run() -> None:
        data = {CONF_ACCESS_TOKEN: "access-token"}
        entry = SimpleNamespace(data=data)
        update_entry = MagicMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry),
        )
        coordinator = SimpleNamespace(hass=hass, config_entry=entry)
        monkeypatch.setattr(
            integration,
            "_async_get_valid_entry_data",
            AsyncMock(return_value=dict(data)),
        )

        await integration.ClaudeUsageCoordinator._ensure_valid_token(coordinator)

        update_entry.assert_not_called()

    asyncio.run(run())
