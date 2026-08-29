"""Tests for Claude account profile helpers."""

import asyncio

import pytest

from custom_components.hass_claude_usage import api
from custom_components.hass_claude_usage.api import (
    ClaudeAccountInfo,
    parse_account_profile,
)


def test_parse_account_profile_uses_selected_team_organization() -> None:
    """Use the selected organization with its account identity."""
    info = parse_account_profile(
        {
            "account": {
                "uuid": "account-a",
                "display_name": "Alice",
                "email": "alice@example.com",
                "has_claude_max": True,
            },
            "organization": {
                "uuid": "team-org",
                "name": "Example Team",
                "organization_type": "claude_team",
            },
        }
    )

    assert info == ClaudeAccountInfo(
        "account-a", "Alice", "team-org", "Example Team", "claude_team", "Team"
    )
    assert info is not None
    assert api.account_organization_id(info) == "account-a:team-org"


def test_parse_account_profile_requires_uuid() -> None:
    """Ignore profiles that do not provide a stable account identity."""
    assert (
        parse_account_profile(
            {
                "account": {"email": "alice@example.com"},
                "organization": {"uuid": "org-a"},
            }
        )
        is None
    )


def test_parse_account_profile_requires_organization_uuid() -> None:
    """Ignore profiles that do not provide a selected organization identity."""
    assert parse_account_profile({"account": {"uuid": "account-a"}}) is None


@pytest.mark.parametrize("account_uuid", ["", "   ", "\t\r\n"])
def test_parse_account_profile_rejects_blank_uuid(account_uuid: str) -> None:
    """Reject UUID values that contain no non-whitespace characters."""
    assert (
        parse_account_profile(
            {
                "account": {"uuid": account_uuid},
                "organization": {"uuid": "org-a"},
            }
        )
        is None
    )


@pytest.mark.parametrize("organization_uuid", ["", "   ", "\t\r\n"])
def test_parse_account_profile_rejects_blank_organization_uuid(
    organization_uuid: str,
) -> None:
    """Reject organization UUID values that contain no non-whitespace characters."""
    assert (
        parse_account_profile(
            {
                "account": {"uuid": "account-a"},
                "organization": {"uuid": organization_uuid},
            }
        )
        is None
    )


def test_parse_account_profile_strips_uuid_whitespace() -> None:
    """Normalize incidental whitespace around stable UUIDs."""
    info = parse_account_profile(
        {
            "account": {"uuid": "  account-a\t"},
            "organization": {"uuid": "  org-a\t"},
        }
    )

    assert info == ClaudeAccountInfo("account-a", None, "org-a", None, None, None)


def test_parse_account_profile_detects_pro_subscription() -> None:
    """Report Pro when the account has a Claude Pro subscription."""
    info = parse_account_profile(
        {
            "account": {"uuid": "account-b", "has_claude_pro": True},
            "organization": {"uuid": "org-b"},
        }
    )

    assert info == ClaudeAccountInfo("account-b", None, "org-b", None, None, "Pro")


@pytest.mark.parametrize(
    ("organization_type", "subscription_level"),
    [
        ("claude_max", "Max"),
        ("claude_pro", "Pro"),
        ("claude_team", "Team"),
        ("claude_enterprise", "Enterprise"),
    ],
)
def test_parse_account_profile_maps_organization_subscription(
    organization_type: str, subscription_level: str
) -> None:
    """Map known organization types to subscription display labels."""
    info = parse_account_profile(
        {
            "account": {"uuid": "account-a"},
            "organization": {"uuid": "org-a", "organization_type": organization_type},
        }
    )

    assert info is not None
    assert info.subscription_level == subscription_level


def test_async_fetch_account_info_returns_none_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat profile request timeouts as an unavailable account profile."""

    class TimeoutSession:
        async def get(self, *args: object, **kwargs: object) -> None:
            raise TimeoutError

    monkeypatch.setattr(
        api.aiohttp_client, "async_get_clientsession", lambda hass: TimeoutSession()
    )

    assert asyncio.run(api.async_fetch_account_info(object(), "access-token")) is None
