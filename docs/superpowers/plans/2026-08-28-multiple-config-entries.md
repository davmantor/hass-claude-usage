# Multiple Claude Account Config Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow separate Home Assistant config entries for different Claude accounts while preventing duplicate accounts and migrating the existing legacy entry automatically.

**Architecture:** Resolve account identity from `account.uuid` through one shared profile API helper. New and reauthentication flows use that UUID with Home Assistant's config-flow uniqueness helpers; a version 1-to-2 migration refreshes credentials without committing partial data, resolves the UUID, and atomically updates the legacy entry.

**Tech Stack:** Python 3.12, Home Assistant config entries and DataUpdateCoordinator, aiohttp, pytest, unittest.mock.

## Global Constraints

- Use `account.uuid` only; do not fall back to account name or email.
- Preserve all unrelated config-entry data and options during migration.
- Do not change sensor definitions, device identifiers, entity identifiers, or polling behavior.
- Use major release version numbers only; this implementation does not create a release or change `manifest.json` version.
- Keep commits atomic and code short, simple, and readable.

---

### Task 1: Shared Account Profile Identity

**Files:**
- Create: `custom_components/hass_claude_usage/api.py`
- Modify: `custom_components/hass_claude_usage/const.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Produces: `ClaudeAccountInfo(account_uuid: str, account_name: str | None, subscription_level: str | None)`.
- Produces: `parse_account_profile(profile: dict[str, Any]) -> ClaudeAccountInfo | None`.
- Produces: `async_fetch_account_info(hass: HomeAssistant, access_token: str) -> ClaudeAccountInfo | None`.
- Produces: `CONF_ACCOUNT_UUID = "account_uuid"`.

- [ ] **Step 1: Write failing profile parsing tests**

Cover a complete profile, a missing UUID, and subscription detection. The complete-profile assertion must require the UUID rather than accepting the display name or email as identity.

```python
def test_parse_account_profile_uses_account_uuid() -> None:
    info = parse_account_profile({
        "account": {
            "uuid": "account-a",
            "display_name": "Alice",
            "email": "alice@example.com",
            "has_claude_max": True,
        }
    })
    assert info == ClaudeAccountInfo("account-a", "Alice", "Max")


def test_parse_account_profile_requires_uuid() -> None:
    assert parse_account_profile({"account": {"email": "alice@example.com"}}) is None
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `py -3.12 -m pytest tests/test_api.py -q`

Expected: collection fails because `custom_components.hass_claude_usage.api` does not exist.

- [ ] **Step 3: Implement the minimal account profile API helper**

Add the frozen account-info dataclass, pure profile parser, and shared aiohttp GET using `PROFILE_API_URL`, `API_BETA_HEADER`, Home Assistant's shared client session, and the existing 15-second timeout. Return `None` for non-success responses, client errors, malformed JSON structures, and missing UUID.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_api.py -q`

Expected: all profile parsing tests pass.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/hass_claude_usage/api.py custom_components/hass_claude_usage/const.py tests/test_api.py
git commit -m "Add stable Claude account identity"
```

### Task 2: Multi-Account Setup and Safe Reauthentication

**Files:**
- Modify: `custom_components/hass_claude_usage/config_flow.py`
- Modify: `custom_components/hass_claude_usage/strings.json`
- Modify: `custom_components/hass_claude_usage/translations/en.json`
- Create: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `async_fetch_account_info` and `ClaudeAccountInfo` from Task 1.
- Consumes: `CONF_ACCOUNT_UUID` from Task 1.
- Produces: config entries whose `unique_id` and stored `account_uuid` equal the profile's `account.uuid`.
- Produces: reauthentication that calls `_abort_if_unique_id_mismatch("wrong_account")` before updating entry data.

- [ ] **Step 1: Write failing new-entry tests**

Mock only token exchange and the external profile request. Invoke `async_step_user` on two flow instances with profile UUIDs `account-a` and `account-b`; assert their calls to `async_set_unique_id` receive different UUIDs and their created entry data stores the corresponding `account_uuid`. Add a duplicate test asserting `_abort_if_unique_id_configured()` is called after the UUID is set.

- [ ] **Step 2: Run the new-entry tests and verify RED**

Run: `py -3.12 -m pytest tests/test_config_flow.py -q`

Expected: assertions fail because both flows currently set the unique ID to `hass_claude_usage` and do not store `account_uuid`.

- [ ] **Step 3: Implement account-specific new entries**

Set `ClaudeUsageConfigFlow.VERSION = 2`. Replace the local profile-fetch implementation with `async_fetch_account_info`. If it returns `None`, set `errors["base"] = "profile_failed"` and do not create an entry. Otherwise set the unique ID to `info.account_uuid`, abort duplicates, and store all account metadata.

- [ ] **Step 4: Run new-entry tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_config_flow.py -q`

Expected: new-entry and duplicate tests pass.

- [ ] **Step 5: Write failing reauthentication tests**

Assert same-account reauthentication calls `async_set_unique_id(existing_uuid)`, then `_abort_if_unique_id_mismatch("wrong_account")`, then updates tokens and account metadata. Simulate a mismatching UUID by making the mismatch helper raise Home Assistant's abort exception; assert entry update is never called.

- [ ] **Step 6: Run reauthentication tests and verify RED**

Run: `py -3.12 -m pytest tests/test_config_flow.py -q`

Expected: mismatch assertions fail because reauthentication currently performs no account identity validation.

- [ ] **Step 7: Implement safe reauthentication and translations**

Require profile identity after token exchange, call `async_set_unique_id(info.account_uuid)` and `_abort_if_unique_id_mismatch("wrong_account")`, then update the existing entry. Add clear `profile_failed` and `wrong_account` strings to both translation files.

- [ ] **Step 8: Run config-flow tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_config_flow.py -q`

Expected: all config-flow tests pass.

- [ ] **Step 9: Commit**

```powershell
git add custom_components/hass_claude_usage/config_flow.py custom_components/hass_claude_usage/strings.json custom_components/hass_claude_usage/translations/en.json tests/test_config_flow.py
git commit -m "Support multiple Claude account entries"
```

### Task 3: Atomic Legacy Entry Migration

**Files:**
- Modify: `custom_components/hass_claude_usage/__init__.py`
- Create: `tests/test_migration.py`

**Interfaces:**
- Consumes: `async_fetch_account_info` and `CONF_ACCOUNT_UUID` from Tasks 1 and 2.
- Produces: `_async_get_valid_entry_data(hass, entry) -> dict[str, Any]`, which returns refreshed entry data without writing it.
- Produces: `async_migrate_entry(hass, entry) -> bool`, which migrates version 1 entries atomically to version 2.

- [ ] **Step 1: Write failing migration-success test**

Create a version 1 fake entry with legacy unique ID `hass_claude_usage`, existing tokens, options, and unrelated data. Mock token validation and profile lookup, invoke `async_migrate_entry`, and assert one `async_update_entry` call contains the merged data, `unique_id="account-a"`, and `version=2` while options remain untouched.

- [ ] **Step 2: Run migration-success test and verify RED**

Run: `py -3.12 -m pytest tests/test_migration.py::test_migrates_legacy_entry_to_account_uuid -q`

Expected: import or attribute failure because `async_migrate_entry` does not exist.

- [ ] **Step 3: Extract non-mutating token validation and implement migration**

Move refresh request logic into `_async_get_valid_entry_data`. It returns a copied data mapping when the token is current or a copied mapping containing refreshed tokens when expired, but never calls `async_update_entry`. Make coordinator `_ensure_valid_token` commit returned data only when it differs. Implement migration so it first resolves valid data and profile identity, then makes one `async_update_entry` call with data, UUID, and version.

- [ ] **Step 4: Run migration-success test and verify GREEN**

Run: `py -3.12 -m pytest tests/test_migration.py::test_migrates_legacy_entry_to_account_uuid -q`

Expected: the migration-success test passes.

- [ ] **Step 5: Write failing no-partial-migration tests**

Cover token validation failure and profile identity failure. Assert `async_migrate_entry` returns `False` and `async_update_entry` is not called in either case. Add a version 2 no-op test that returns `True` without requests or writes.

- [ ] **Step 6: Run migration failure tests and verify RED**

Run: `py -3.12 -m pytest tests/test_migration.py -q`

Expected: at least one failure until failure handling and the version 2 no-op are present.

- [ ] **Step 7: Complete migration failure handling**

Catch `ConfigEntryAuthFailed` and `UpdateFailed` from token validation, return `False` for a missing profile identity, log concise reasons, and leave the entry untouched. Return `True` immediately for entries already at version 2.

- [ ] **Step 8: Run migration tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_migration.py -q`

Expected: all migration tests pass.

- [ ] **Step 9: Commit**

```powershell
git add custom_components/hass_claude_usage/__init__.py tests/test_migration.py
git commit -m "Migrate legacy Claude account entry"
```

### Task 4: Full Verification

**Files:**
- Modify only if verification exposes a defect in the scoped implementation.

**Interfaces:**
- Consumes all behavior from Tasks 1 through 3.
- Produces a verified multi-account integration change.

- [ ] **Step 1: Run the complete supported-version test suite**

Run: `py -3.12 -m pytest -q`

Expected: all tests pass with no collection errors.

- [ ] **Step 2: Run lint and formatting checks**

Run: `py -3.12 -m ruff check custom_components tests`

Run: `py -3.12 -m black --check custom_components tests`

Expected: both commands exit successfully with no violations.

- [ ] **Step 3: Inspect the final diff and repository state**

Run: `git diff HEAD~3 --check`

Run: `git status --short`

Expected: no whitespace errors; only intentionally untracked local cache files may remain, and all feature files are committed.

- [ ] **Step 4: Report migration behavior and installation consequence**

State that a restart or integration reload after installing the new release triggers migration, different account UUIDs can coexist, duplicate UUIDs are rejected, and wrong-account reauthentication is blocked.
