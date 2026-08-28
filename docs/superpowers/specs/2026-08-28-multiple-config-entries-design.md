# Organization-Scoped Claude Usage Entries

## Goal

Allow one Home Assistant instance to configure multiple Claude Usage entries for distinct account-and-organization pairs. This includes a personal subscription and a Team organization selected through Anthropic's existing OAuth organization picker under the same Claude account.

Reject only duplicate selections of the same account and organization. Automatically migrate existing version 1 and version 2 entries.

## Identity

The OAuth profile response identifies both scopes:

- `account.uuid` identifies the Claude login.
- `organization.uuid` identifies the selected subscription or Team organization.

Require both UUIDs after trimming whitespace. The stable Home Assistant config-entry unique ID is the unambiguous composite:

```text
<account_uuid>:<organization_uuid>
```

Do not use names, email addresses, or subscription labels as identity. Store both UUIDs and the available account and organization display metadata in config-entry data.

## OAuth and New Entry Flow

Keep the current OAuth URL and manual authorization-code flow. Anthropic's authorization screen already lets the user select an organization, so the integration must not ask for an organization UUID or add its own organization-selection step.

After exchanging the authorization code:

1. Fetch `/api/oauth/profile` with the issued token.
2. Parse the selected account UUID, organization UUID, account name, organization name, and organization type.
3. Derive the subscription label from `organization.organization_type` first, with the existing account flags as a compatibility fallback.
4. Set the config-flow unique ID to the account-and-organization composite.
5. Abort only if that composite is already configured.
6. Store the tokens, expiry, both UUIDs, and display metadata.

The entry and device title should include enough organization context to distinguish two entries for the same account. Prefer the organization name; include the account name and subscription label when available without duplicating identical text.

If either required UUID is missing or malformed, show the existing profile failure and do not create an entry.

## Reauthentication

After replacement OAuth authorization, fetch the profile and build the same composite identity. Call `_abort_if_unique_id_mismatch("wrong_account")` before updating any credentials.

This treats selecting a different organization during reauthentication as the wrong identity, even when the account UUID is unchanged. On success, update tokens, expiry, and all current account/organization metadata, then reload the same entry.

## Migration to Version 3

Increase `ConfigFlow.VERSION` from 2 to 3.

For version 1 and version 2 entries:

1. Obtain valid entry data without writing it, refreshing the token when needed.
2. Fetch the profile and require both account and organization UUIDs.
3. Build the composite unique ID.
4. Check whether another entry already owns that composite.
5. Perform one `async_update_entry` call that stores refreshed data and metadata, changes the unique ID, updates the title if organization context is available, and sets version 3.

Version 1 entries may have the legacy domain-wide unique ID. Version 2 entries have an account-only unique ID. Both migrate through the same profile-derived path.

Version 3 entries are a successful no-op. Unsupported versions fail without requests or writes. Token, profile, or identity failures leave the original entry unchanged.

## Shared Profile Model

Extend the existing `ClaudeAccountInfo` model rather than adding a parallel organization model. It should contain:

- account UUID
- account display name
- organization UUID
- organization name
- organization type
- user-facing subscription level

Profile parsing remains centralized in `api.py`, so setup, migration, and reauthentication use identical validation and identity construction.

Add constants for stored organization UUID, name, and type. A small pure helper should build the composite identity so tests and all lifecycle paths use the exact same format.

## Existing Runtime Behavior

Keep coordinator isolation, entity unique IDs, device identifiers, polling, sensors, and options unchanged. They are already scoped by `entry.runtime_data` and `entry.entry_id`, so two organization entries can run independently once the config flow admits them.

## Tests

Add or update regression coverage proving:

1. The profile parser requires and normalizes both account and organization UUIDs.
2. The subscription label follows the selected organization type, including Team.
3. The same account with two organization UUIDs creates two entries through the real Home Assistant flow manager.
4. The same account-and-organization pair is rejected as a duplicate.
5. Profile failure prevents entry creation.
6. Reauthentication succeeds for the same composite identity.
7. Reauthentication with the same account but a different organization aborts as `wrong_account` without changing the entry.
8. Real registered version 1 and version 2 entries migrate to version 3 and are reindexed under the composite identity.
9. Migration collision and failure paths make no partial writes.
10. Existing coordinator, sensor, and helper tests remain green.

Run focused red-green cycles, then the complete test suite, Ruff, Black, Python compilation, JSON validation, and a Git whitespace check.

## Documentation

Update project design notes to state that multiple organizations under one Claude account are supported when Anthropic's OAuth picker issues organization-scoped tokens. Retain the limitation that the integration cannot enumerate organizations itself; it uses only the organization selected during OAuth.

## Non-Goals

- Building a separate organization browser or asking users to discover UUIDs manually.
- Combining multiple organizations into one config entry or device.
- Changing the undocumented Anthropic OAuth client or usage endpoints.
- Changing sensor definitions, entity IDs, device identifiers, or polling behavior.
