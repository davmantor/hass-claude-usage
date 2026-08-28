"""Claude account profile API helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .const import API_BETA_HEADER, PROFILE_API_URL


@dataclass(frozen=True)
class ClaudeAccountInfo:
    """Stable account identity and optional display information."""

    account_uuid: str
    account_name: str | None
    subscription_level: str | None


def parse_account_profile(profile: dict[str, Any]) -> ClaudeAccountInfo | None:
    """Parse a profile response when it provides a stable account UUID."""
    account = profile.get("account")
    if not isinstance(account, dict):
        return None

    account_uuid = account.get("uuid")
    if not isinstance(account_uuid, str) or not account_uuid:
        return None

    account_name = account.get("display_name") or account.get("full_name") or account.get("email")
    if not isinstance(account_name, str):
        account_name = None

    subscription_level = None
    if account.get("has_claude_max"):
        subscription_level = "Max"
    elif account.get("has_claude_pro"):
        subscription_level = "Pro"

    return ClaudeAccountInfo(account_uuid, account_name, subscription_level)


async def async_fetch_account_info(
    hass: HomeAssistant, access_token: str
) -> ClaudeAccountInfo | None:
    """Fetch the stable account identity from the Claude profile API."""
    try:
        session = aiohttp_client.async_get_clientsession(hass)
        response = await session.get(
            PROFILE_API_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "anthropic-beta": API_BETA_HEADER,
            },
            timeout=aiohttp.ClientTimeout(total=15),
        )
        if not response.ok:
            return None
        profile = await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, TypeError, ValueError):
        return None

    if not isinstance(profile, dict):
        return None
    return parse_account_profile(profile)
