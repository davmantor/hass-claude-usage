# Organization-Scoped Claude Usage Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the same Claude account to create separate Home Assistant entries for personal and Team organizations selected during OAuth.

**Architecture:** Extend the shared profile model with the selected organization identity and use `<account_uuid>:<organization_uuid>` everywhere Home Assistant needs stable config-entry identity. Existing version 1 and version 2 entries migrate atomically to version 3 after profile lookup, while runtime coordinator and entity isolation remain entry-scoped.

**Tech Stack:** Python 3.12, Home Assistant config entries and DataUpdateCoordinator, aiohttp, pytest, Ruff, Black.

## Global Constraints

- Require both `account.uuid` and `organization.uuid`; never use names or email as identity.
- Keep the current OAuth organization picker; do not ask users for organization UUIDs.
- Use the exact composite unique ID `<account_uuid>:<organization_uuid>`.
- Preserve unrelated config-entry data and options during migration.
- Do not change sensor definitions, entity IDs, device identifiers, polling behavior, or `manifest.json` release version.
- Keep commits atomic and code short, simple, and readable.

---

### Task 1: Organization-Aware Profile Identity

**Files:**
- Modify: `custom_components/hass_claude_usage/api.py`
- Modify: `custom_components/hass_claude_usage/const.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Produces: `ClaudeAccountInfo(account_uuid: str, account_name: str | None, organization_uuid: str, organization_name: str | None, organization_type: str | None, subscription_level: str | None)`.
- Produces: `account_organization_id(info: ClaudeAccountInfo) -> str` returning exactly `f"{info.account_uuid}:{info.organization_uuid}"`.
- Produces: `CONF_ORGANIZATION_UUID`, `CONF_ORGANIZATION_NAME`, and `CONF_ORGANIZATION_TYPE`.

- [ ] **Step 1: Write failing organization profile tests**

Add tests requiring a nonblank organization UUID, trimming both UUIDs, parsing organization name/type, mapping `claude_team` to `Team`, and proving organization type takes precedence over account-level Max/Pro flags.

```python
def test_parse_account_profile_uses_selected_team_organization() -> None:
    info = parse_account_profile({
        "account": {"uuid": "account-a", "display_name": "Alice", "has_claude_max": True},
        "organization": {
            "uuid": "team-org",
            "name": "Example Team",
            "organization_type": "claude_team",
        },
    })
    assert info == ClaudeAccountInfo(
        "account-a", "Alice", "team-org", "Example Team", "claude_team", "Team"
    )
    assert account_organization_id(info) == "account-a:team-org"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `py -3.12 -m pytest tests/test_api.py -q`

Expected: failures because the profile model does not contain organization fields and account-only profiles are currently accepted.

- [ ] **Step 3: Implement minimal organization parsing and identity**

Extend the frozen dataclass, require/trim both UUIDs, parse organization metadata, and map known organization types (`claude_max`, `claude_pro`, `claude_team`, `claude_enterprise`) to display labels before falling back to account flags. Add the pure composite-ID helper and constants.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_api.py -q`

Expected: all profile and request-failure tests pass.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/hass_claude_usage/api.py custom_components/hass_claude_usage/const.py tests/test_api.py
git commit -m "Add Claude organization identity"
```

### Task 2: Organization-Scoped Setup and Reauthentication

**Files:**
- Modify: `custom_components/hass_claude_usage/config_flow.py`
- Modify: `custom_components/hass_claude_usage/sensor.py`
- Modify: `custom_components/hass_claude_usage/binary_sensor.py`
- Modify: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `ClaudeAccountInfo` and `account_organization_id` from Task 1.
- Consumes: all account and organization config constants.
- Produces: version 3 config entries keyed by the account-and-organization composite.

- [ ] **Step 1: Write failing real flow-manager tests**

Update fixtures to return organization-aware profiles. Add coverage proving the same account with `personal-org` and `team-org` creates two entries with unique IDs `account-a:personal-org` and `account-a:team-org`, while the same pair aborts as already configured. Assert stored organization metadata and distinct titles.

- [ ] **Step 2: Run setup tests and verify RED**

Run: `py -3.12 -m pytest tests/test_config_flow.py -q`

Expected: failures because both entries still use the account-only unique ID.

- [ ] **Step 3: Implement organization-scoped setup**

Set `ClaudeUsageConfigFlow.VERSION = 3`. Build the unique ID with `account_organization_id`, store all organization metadata, and include organization context in the entry title. Keep the OAuth URL unchanged so Anthropic's existing organization picker remains authoritative.

- [ ] **Step 4: Run setup tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_config_flow.py -q`

Expected: setup, duplicate, and profile-failure tests pass.

- [ ] **Step 5: Write failing organization reauthentication tests**

Using the real flow manager, prove reauthentication succeeds for the same account-and-organization composite and aborts with `wrong_account` when the account matches but the selected organization differs. Assert no credential or metadata update on mismatch.

- [ ] **Step 6: Run reauthentication tests and verify RED**

Run: `py -3.12 -m pytest tests/test_config_flow.py -q`

Expected: mismatch behavior fails while identity remains account-only.

- [ ] **Step 7: Implement reauthentication and device-title metadata**

Use the composite identity before `_abort_if_unique_id_mismatch`, update organization metadata on success, and include stored organization name in sensor and binary-sensor device names so two entries for one account are distinguishable.

- [ ] **Step 8: Run tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_config_flow.py -q`

Run: `py -3.12 -m pytest -q`

Expected: focused and full suites pass.

- [ ] **Step 9: Commit**

```powershell
git add custom_components/hass_claude_usage/config_flow.py custom_components/hass_claude_usage/sensor.py custom_components/hass_claude_usage/binary_sensor.py tests/test_config_flow.py
git commit -m "Scope Claude entries by organization"
```

### Task 3: Version 3 Migration and Documentation

**Files:**
- Modify: `custom_components/hass_claude_usage/__init__.py`
- Modify: `tests/test_migration.py`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: organization-aware profile data and `account_organization_id`.
- Produces: `async_migrate_entry` support for versions 1 and 2 to version 3.

- [ ] **Step 1: Write failing registered-entry migration tests**

Add real registered `ConfigEntry` cases for version 1 and version 2. For both, return the same account/team profile and assert migration changes the unique ID to `account-a:team-org`, stores organization metadata, preserves unrelated data/options, updates the title with organization context, reindexes the registry, and sets version 3.

- [ ] **Step 2: Run migration success tests and verify RED**

Run: `py -3.12 -m pytest tests/test_migration.py -q`

Expected: failures because version 2 is currently a no-op and migration targets version 2/account-only identity.

- [ ] **Step 3: Implement v1/v2 to v3 migration**

Accept only versions 1 and 2 for migration, treat version 3 as a successful no-op, reject other versions, build/check the composite owner, and perform one atomic `async_update_entry` with merged data, title, unique ID, and `version=3`.

- [ ] **Step 4: Run migration success tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_migration.py -q`

Expected: registered v1 and v2 migration tests pass.

- [ ] **Step 5: Write or update collision and failure tests**

Prove another entry owning the same composite blocks migration with zero writes; different organizations under the same account do not collide; profile/token failures remain atomic; version 3 is a no-op; version 4 is rejected.

- [ ] **Step 6: Run failure tests and verify RED, then implement minimal corrections**

Run: `py -3.12 -m pytest tests/test_migration.py -q`

Expected before correction: at least the different-organization ownership or unsupported-version expectation fails. Make only the changes required for the specified outcomes.

- [ ] **Step 7: Update project design notes**

Document that one account can have multiple organization-scoped entries selected through OAuth. Replace the old multiple-organization limitation with the narrower limitation that the integration cannot enumerate organizations independently of the OAuth picker.

- [ ] **Step 8: Run focused and full verification**

Run: `py -3.12 -m pytest tests/test_migration.py -q`

Run: `py -3.12 -m pytest -q`

Expected: all tests pass.

- [ ] **Step 9: Commit**

```powershell
git add custom_components/hass_claude_usage/__init__.py tests/test_migration.py AGENTS.md
git commit -m "Migrate Claude entries to organization scope"
```

### Task 4: Full Verification and Review

**Files:**
- Modify only if verification or review exposes a scoped defect.

- [ ] **Step 1: Run quality checks**

Run: `uvx ruff check custom_components tests`

Run: `uvx black --check custom_components tests`

Run: `py -3.12 -m pytest -q`

Run: `py -3.12 -m compileall -q custom_components tests`

Parse all integration JSON files and run `git diff origin/main..HEAD --check`.

Expected: every command exits zero; only known third-party deprecation warnings may remain.

- [ ] **Step 2: Request final whole-change review**

Review organization identity, OAuth-selected scope, duplicate behavior, reauthentication, v1/v2 migration atomicity, registry reindexing, and unchanged runtime entity behavior. Fix all Critical and Important findings, then re-review.

- [ ] **Step 3: Report deployment behavior**

State that installing and reloading the integration migrates existing entries to organization scope. A user can then run setup again, choose another organization in Anthropic's OAuth screen, and create a second entry for the same account.
