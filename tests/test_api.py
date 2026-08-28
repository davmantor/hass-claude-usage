"""Tests for Claude account profile helpers."""

import asyncio

import pytest

from custom_components.hass_claude_usage import api
from custom_components.hass_claude_usage.api import ClaudeAccountInfo, parse_account_profile


def test_parse_account_profile_uses_account_uuid() -> None:
    """Use the account UUID, rather than display data, as the identity."""
    info = parse_account_profile(
        {
            "account": {
                "uuid": "account-a",
                "display_name": "Alice",
                "email": "alice@example.com",
                "has_claude_max": True,
            }
        }
    )

    assert info == ClaudeAccountInfo("account-a", "Alice", "Max")


def test_parse_account_profile_requires_uuid() -> None:
    """Ignore profiles that do not provide a stable account identity."""
    assert parse_account_profile({"account": {"email": "alice@example.com"}}) is None


@pytest.mark.parametrize("account_uuid", ["", "   ", "\t\r\n"])
def test_parse_account_profile_rejects_blank_uuid(account_uuid: str) -> None:
    """Reject UUID values that contain no non-whitespace characters."""
    assert parse_account_profile({"account": {"uuid": account_uuid}}) is None


def test_parse_account_profile_strips_uuid_whitespace() -> None:
    """Normalize incidental whitespace around the stable account UUID."""
    info = parse_account_profile({"account": {"uuid": "  account-a\t"}})

    assert info == ClaudeAccountInfo("account-a", None, None)


def test_parse_account_profile_detects_pro_subscription() -> None:
    """Report Pro when the account has a Claude Pro subscription."""
    info = parse_account_profile({"account": {"uuid": "account-b", "has_claude_pro": True}})

    assert info == ClaudeAccountInfo("account-b", None, "Pro")


def test_async_fetch_account_info_returns_none_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat profile request timeouts as an unavailable account profile."""

    class TimeoutSession:
        async def get(self, *args: object, **kwargs: object) -> None:
            raise asyncio.TimeoutError

    monkeypatch.setattr(api.aiohttp_client, "async_get_clientsession", lambda hass: TimeoutSession())

    assert asyncio.run(api.async_fetch_account_info(object(), "access-token")) is None
