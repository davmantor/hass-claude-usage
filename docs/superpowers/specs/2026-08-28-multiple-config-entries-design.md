# Multiple Claude Account Config Entries

## Goal

Allow one Home Assistant instance to configure multiple Claude Usage entries when each entry belongs to a different Claude account. Continue to reject duplicate entries for the same Claude account, and automatically migrate the existing legacy entry.

## Account Identity

Use `account.uuid` from `GET /api/oauth/profile` as the stable account identifier. Display names and email addresses are not suitable identifiers because names can collide or change and email addresses can change.

Add an `account_uuid` value to config-entry data so the resolved identity is available for diagnostics and future migrations. Set the Home Assistant config-entry `unique_id` to the same account UUID.

Profile data is required to create or reauthenticate an entry. If the profile response is unavailable, malformed, or lacks `account.uuid`, the flow must report an error and must not create or modify an entry.

## New Entry Flow

After exchanging the OAuth authorization code, fetch the account profile and extract the account UUID, display name, and subscription level. Set the flow unique ID to the account UUID and call `_abort_if_unique_id_configured()` before creating the entry.

This behavior permits different account UUIDs and rejects a second entry for an already configured UUID. The entry stores its tokens, token expiry, account UUID, account name, subscription level, and polling option.

## Existing Entry Migration

Increase the config-flow version from 1 to 2 and implement `async_migrate_entry`.

For a version 1 entry, obtain a valid access token, refreshing it with the stored refresh token when necessary. Fetch the account profile and require `account.uuid`. After all required data has been obtained, update the entry through `hass.config_entries.async_update_entry` in one operation:

- Set `unique_id` to the account UUID.
- Store `account_uuid`, along with the current account display and subscription metadata.
- Preserve all unrelated entry data and options.
- Set the entry version to 2.

If token refresh or profile lookup fails, return a failed migration without changing the entry. Home Assistant can retry after authentication or connectivity is restored. No partial migration is allowed.

## Reauthentication

After exchanging the replacement authorization code, fetch the profile and set the flow unique ID to its account UUID. Call `_abort_if_unique_id_mismatch("wrong_account")` before updating the entry. This prevents a user from silently replacing one configured account with another account during reauthentication.

On success, update the tokens, expiry, account UUID, display name, and subscription level, then reload the same entry.

## Code Structure

Keep the change focused and small:

- Add `CONF_ACCOUNT_UUID` to `const.py`.
- Change profile parsing in `config_flow.py` to return a small structured result containing UUID, name, and subscription level.
- Reuse the same profile parsing and request behavior in setup, migration, and reauthentication rather than implementing three field-extraction paths.
- Keep coordinator, entity, device, and options handling unchanged because they are already scoped by `entry.runtime_data` and `entry.entry_id`.

## Error Handling

New setup and reauthentication show a specific profile/identity error when the profile cannot provide a UUID. OAuth token exchange errors retain their existing behavior.

Migration logs the reason and returns `False` if credentials cannot be refreshed or account identity cannot be fetched. It does not overwrite the old unique ID, entry data, or version on failure.

## Tests

Add regression coverage that proves:

1. Two OAuth profiles with different account UUIDs can create two entries.
2. A second setup using an already configured account UUID aborts as already configured.
3. A version 1 entry migrates to version 2, receives the account UUID as its unique ID, and retains its existing data and options.
4. A failed identity lookup leaves a version 1 entry unchanged and reports migration failure.
5. Reauthentication with the same account UUID updates and reloads the entry.
6. Reauthentication with a different account UUID aborts with `wrong_account` and does not modify the entry.

Run the focused config-flow and migration tests first, followed by the complete available test suite and lint checks under the project's supported Python version.

## Non-Goals

- Supporting multiple organizations under one Claude account.
- Changing sensor definitions, entity IDs, device grouping, or polling behavior.
- Allowing duplicate entries for the same Claude account.
- Falling back to display name or email when `account.uuid` is missing.
