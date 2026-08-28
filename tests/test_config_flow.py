"""Tests for the Claude Usage configuration flow."""

import asyncio
from typing import Any

import pytest
from homeassistant.data_entry_flow import AbortFlow

from custom_components.hass_claude_usage import config_flow
from custom_components.hass_claude_usage.api import ClaudeAccountInfo
from custom_components.hass_claude_usage.const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_NAME,
    CONF_ACCOUNT_UUID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_SUBSCRIPTION_LEVEL,
)


def _token_data() -> dict[str, Any]:
    return {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 3600,
    }


def _new_flow(
    monkeypatch: pytest.MonkeyPatch,
    info: ClaudeAccountInfo,
    events: list[tuple[str, Any]],
) -> config_flow.ClaudeUsageConfigFlow:
    flow = config_flow.ClaudeUsageConfigFlow()

    async def exchange_code(code: str) -> dict[str, Any]:
        return _token_data()

    async def set_unique_id(unique_id: str) -> None:
        events.append(("unique_id", unique_id))

    async def fetch_account_info(hass: object, access_token: str) -> ClaudeAccountInfo:
        return info

    def abort_if_configured() -> None:
        events.append(("abort_if_configured", None))

    def create_entry(**kwargs: Any) -> dict[str, Any]:
        events.append(("create_entry", kwargs))
        return kwargs

    monkeypatch.setattr(flow, "_exchange_code", exchange_code)
    monkeypatch.setattr(flow, "async_set_unique_id", set_unique_id)
    monkeypatch.setattr(flow, "_abort_if_unique_id_configured", abort_if_configured)
    monkeypatch.setattr(flow, "async_create_entry", create_entry)
    monkeypatch.setattr(config_flow, "async_fetch_account_info", fetch_account_info, raising=False)
    return flow


def test_user_flows_create_entries_for_their_profile_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow separately authenticated Claude accounts to create separate entries."""
    first_events: list[tuple[str, Any]] = []
    second_events: list[tuple[str, Any]] = []
    first_flow = _new_flow(
        monkeypatch,
        ClaudeAccountInfo("account-a", "Alice", "Max"),
        first_events,
    )
    first_result = asyncio.run(first_flow.async_step_user({"auth_code": "first-code"}))

    second_flow = _new_flow(
        monkeypatch,
        ClaudeAccountInfo("account-b", "Bob", "Pro"),
        second_events,
    )
    second_result = asyncio.run(second_flow.async_step_user({"auth_code": "second-code"}))

    assert first_events[0] == ("unique_id", "account-a")
    assert second_events[0] == ("unique_id", "account-b")
    assert first_result["data"][CONF_ACCOUNT_UUID] == "account-a"
    assert second_result["data"][CONF_ACCOUNT_UUID] == "account-b"


def test_user_flow_checks_for_duplicate_after_setting_profile_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check duplicates only after the profile UUID is the flow identity."""
    events: list[tuple[str, Any]] = []
    flow = _new_flow(
        monkeypatch,
        ClaudeAccountInfo("account-a", "Alice", "Max"),
        events,
    )

    asyncio.run(flow.async_step_user({"auth_code": "code"}))

    assert events[:2] == [
        ("unique_id", "account-a"),
        ("abort_if_configured", None),
    ]


def _reauth_flow(
    monkeypatch: pytest.MonkeyPatch,
    info: ClaudeAccountInfo,
    events: list[tuple[str, Any]],
    abort_mismatch: bool = False,
) -> config_flow.ClaudeUsageConfigFlow:
    flow = config_flow.ClaudeUsageConfigFlow()
    entry = object()

    async def exchange_code(code: str) -> dict[str, Any]:
        return _token_data()

    async def fetch_account_info(hass: object, access_token: str) -> ClaudeAccountInfo:
        return info

    async def set_unique_id(unique_id: str) -> None:
        events.append(("unique_id", unique_id))

    def ensure_matching_account(*, reason: str) -> None:
        events.append(("abort_if_unique_id_mismatch", reason))
        if abort_mismatch:
            raise AbortFlow(reason)

    def update_entry(entry: object, **kwargs: Any) -> dict[str, Any]:
        events.append(("update_entry", kwargs))
        return kwargs

    monkeypatch.setattr(flow, "_exchange_code", exchange_code)
    monkeypatch.setattr(flow, "async_set_unique_id", set_unique_id)
    monkeypatch.setattr(flow, "_abort_if_unique_id_mismatch", ensure_matching_account)
    monkeypatch.setattr(flow, "_get_reauth_entry", lambda: entry)
    monkeypatch.setattr(flow, "async_update_reload_and_abort", update_entry)
    monkeypatch.setattr(config_flow, "async_fetch_account_info", fetch_account_info)
    return flow


def test_reauth_updates_tokens_only_after_confirming_same_profile_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh an entry only after confirming the OAuth profile account identity."""
    events: list[tuple[str, Any]] = []
    flow = _reauth_flow(
        monkeypatch,
        ClaudeAccountInfo("account-a", "Alice", "Max"),
        events,
    )

    result = asyncio.run(flow.async_step_reauth_confirm({"auth_code": "code"}))

    assert events[:2] == [
        ("unique_id", "account-a"),
        ("abort_if_unique_id_mismatch", "wrong_account"),
    ]
    assert result["data_updates"][CONF_ACCOUNT_UUID] == "account-a"
    assert result["data_updates"][CONF_ACCOUNT_NAME] == "Alice"
    assert result["data_updates"][CONF_SUBSCRIPTION_LEVEL] == "Max"
    assert result["data_updates"][CONF_ACCESS_TOKEN] == "new-access-token"
    assert result["data_updates"][CONF_REFRESH_TOKEN] == "new-refresh-token"
    assert CONF_EXPIRES_AT in result["data_updates"]


def test_reauth_does_not_update_entry_when_profile_account_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Abort before changing stored credentials for a different Claude account."""
    events: list[tuple[str, Any]] = []
    flow = _reauth_flow(
        monkeypatch,
        ClaudeAccountInfo("account-b", "Bob", "Pro"),
        events,
        abort_mismatch=True,
    )

    with pytest.raises(AbortFlow, match="wrong_account"):
        asyncio.run(flow.async_step_reauth_confirm({"auth_code": "code"}))

    assert events == [
        ("unique_id", "account-b"),
        ("abort_if_unique_id_mismatch", "wrong_account"),
    ]
