"""Tests for Claude account profile helpers."""

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


def test_parse_account_profile_detects_pro_subscription() -> None:
    """Report Pro when the account has a Claude Pro subscription."""
    info = parse_account_profile({"account": {"uuid": "account-b", "has_claude_pro": True}})

    assert info == ClaudeAccountInfo("account-b", None, "Pro")
