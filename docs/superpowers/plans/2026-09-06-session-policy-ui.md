# Session Policy Management UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-user private-chat content-safety policies and redesign the shared group/private policy manager to match the plugin center's Sakura pink-and-white design system.

**Architecture:** Generalize the existing group-only configuration service into two isolated group/private namespaces while preserving the current group API and stored data. Resolve runtime policy by group ID for group messages and sender user ID for private messages, and include both identities in cache keys. Extract browser state transitions into a small ES module so dirty-draft, scope, selection, save, and delete behavior can be tested directly.

**Tech Stack:** Python 3.10+, asyncio, AstrBotConfig, Quart, vanilla HTML/CSS/ES modules, Node test runner, pytest.

## Global Constraints

- Preserve existing `group_content_safety_policies` data and all current group-policy routes.
- Add `private_content_safety_policies`; missing, malformed, deleted, or lookup-failed private policies resolve to strict defaults with ordinary grading and built-in words both enabled.
- Keep group and private drafts, selections, searches, lists, and request state isolated.
- Ask before discarding a dirty draft when changing scope or selecting another record.
- Keep plugin version `v3.6.1`; document the feature without introducing a version bump.
- Match the existing Sakura design tokens and responsive breakpoints at 900 px and 620 px.
- Tests must execute real service, HTTP, and state-transition behavior; token-presence, empty, or wrapper-only tests do not satisfy acceptance.
- Preserve untracked `.pytest-tmp*` directories and unrelated working-tree changes.

---

## File Responsibility Map

- `_conf_schema.json`: AstrBot native configuration templates for group and private policy rows.
- `group_safety.py`: canonical session-policy persistence service plus group compatibility entry points.
- `pixiv/safety.py`: resolved policy value object and cache identity.
- `pixiv/filters.py`: policy-aware filtering and cache use.
- `main.py`: event context extraction and group/private policy resolution.
- `plugin_api/api.py`: management and effective-policy HTTP endpoints.
- `pages/pluginCenter/policy-state.mjs`: pure, executable UI state transitions.
- `pages/pluginCenter/app.js`: API orchestration, dirty-draft confirmation, and DOM rendering.
- `pages/pluginCenter/index.html`: accessible session-policy page structure.
- `pages/pluginCenter/styles.css`: Sakura-aligned desktop and responsive presentation.
- `tests/test_group_safety_config.py`: persistence, normalization, isolation, rollback, and compatibility tests.
- `tests/test_filtering.py`, `tests/test_checkin_calendar.py`: runtime lookup and cache-isolation tests.
- `tests/test_plugin_management_api.py`: real Quart endpoint behavior.
- `tests/js/policy-state.test.mjs`: executable browser-state unit tests.
- `tests/test_plugin_center_frontend.py`: markup, function-body, accessibility, and responsive-contract tests.
- `README.md`, `CHANGELOG.md`, `docs/project/configuration.md`, `docs/project/architecture.md`, `metadata.yaml`: user-facing and architectural documentation.

---

### Task 1: Generalize persistence into group and private namespaces

**Files:**
- Modify: `_conf_schema.json`
- Modify: `group_safety.py`
- Modify: `tests/test_group_safety_config.py`

**Interfaces:**
- Produces: `SessionSafetyService(config)` and methods `list_group_policies()`, `get_group_policy(group_id)`, `upsert_group_policy(group_id, force_general_rating, enable_builtin_words)`, `remove_group_policy(group_id)`, plus symmetric `list_private_policies()`, `get_private_policy(user_id)`, `upsert_private_policy(user_id, force_general_rating, enable_builtin_words)`, and `remove_private_policy(user_id)`.
- Produces: compatibility alias `GroupSafetyService` and legacy `list_policies`, `get_policy`, `upsert_policy`, `remove_policy` methods mapped to group policies.
- Returns: normalized records containing the scope identifier, two booleans, and saved timestamp where currently supported.

- [ ] **Step 1: Write failing persistence tests**

Add tests that construct one config containing both namespaces, insert one group and one private record, update each independently, delete each independently, and assert a missing or malformed record resolves to strict defaults. Add a save-failure test that snapshots the complete config, forces `save_config()` to raise, and asserts both namespaces are restored exactly. Keep the existing group compatibility tests unchanged.

- [ ] **Step 2: Run the focused tests and confirm the new cases fail**

Run: `python -m pytest -q tests/test_group_safety_config.py`

Expected: the newly added private-service tests fail because the private methods and schema entry do not exist; existing group tests pass.

- [ ] **Step 3: Add the private native-config template**

In `_conf_schema.json`, add `private_content_safety_policies` beside `group_content_safety_policies` using the same template-list shape. Its row fields are `user_id` (string), `force_general_rating` (bool, default `true`), and `enable_builtin_words` (bool, default `true`). Labels and hints must explicitly say “用户 ID” and “私聊”.

- [ ] **Step 4: Implement the two-namespace service**

Refactor the current normalization and transactional-save code into scope-aware private helpers. Public group methods pass `group_content_safety_policies` and `group_id`; public private methods pass `private_content_safety_policies` and `user_id`. Normalize identifiers with `str(value).strip()`, reject empty identifiers, coerce only accepted booleans, and use strict defaults whenever a row is absent or invalid. Mutate the injected config in place and restore a deep snapshot on `save_config()` failure.

- [ ] **Step 5: Preserve group compatibility**

Keep `GroupSafetyService` importable and route its original four public methods to the group namespace so existing callers and deployments need no migration.

- [ ] **Step 6: Run and commit the persistence slice**

Run: `python -m pytest -q tests/test_group_safety_config.py`

Expected: all tests pass.

Commit: `feat: add private session safety policies`

---

### Task 2: Resolve private policy at runtime and isolate cache identities

**Files:**
- Modify: `pixiv/safety.py`
- Modify: `pixiv/filters.py`
- Modify: `main.py`
- Modify: `tests/test_filtering.py`
- Modify: `tests/test_checkin_calendar.py`

**Interfaces:**
- Consumes: `SessionSafetyService.get_group_policy(group_id)` and `get_private_policy(user_id)` from Task 1.
- Produces: `ContentSafetyPolicy` with `group_id: str = ""` and `user_id: str = ""`.
- Produces: `ContentSafetyPolicy.cache_identity()` containing policy flags and both normalized identity dimensions.

- [ ] **Step 1: Write failing runtime and cache tests**

Add tests for: a group event using only its group record; a private event using sender user ID; two private users with different policies producing different cache identities; a group and private user sharing the same numeric ID producing different cache identities; absent, malformed, and lookup-error private data resolving to strict flags; and check-in/calendar paths retaining their current defaults.

- [ ] **Step 2: Run the runtime tests and confirm failure**

Run: `python -m pytest -q tests/test_filtering.py tests/test_checkin_calendar.py`

Expected: new user-policy and cache-isolation assertions fail before implementation.

- [ ] **Step 3: Extend the policy value object**

Add `user_id` without changing existing constructor compatibility. Build cache identity from a stable tuple or delimited string containing scope, `group_id`, `user_id`, `force_general_rating`, and `enable_builtin_words`; never let a private user's cached result be reused by another user or by a group with the same digits.

- [ ] **Step 4: Resolve event scope in one place**

In `main.py`, normalize the event group ID and sender user ID once. If group ID is present, query only the group namespace. Otherwise query the private namespace with sender ID. Catch lookup/normalization errors, log concise context without message content, and return strict flags. Pass the selected identity into `ContentSafetyPolicy`.

- [ ] **Step 5: Apply the expanded cache key**

Update filtering/cache call sites to consume `cache_identity()` rather than rebuilding a partial key. Preserve all current filtering semantics beyond identity isolation.

- [ ] **Step 6: Run and commit the runtime slice**

Run: `python -m pytest -q tests/test_filtering.py tests/test_checkin_calendar.py`

Expected: all focused tests pass.

Commit: `feat: apply content safety policies to private chats`

---

### Task 3: Add symmetric private-policy management APIs

**Files:**
- Modify: `plugin_api/api.py`
- Modify: `tests/test_plugin_management_api.py`

**Interfaces:**
- Consumes: group/private service methods from Task 1.
- Produces: `GET content-safety/private-policies`, `POST content-safety/private-policy`, and `POST content-safety/private-policy/remove`.
- Extends: `GET content-safety` with optional `user_id`; exactly one of `group_id` and `user_id` may be supplied.

- [ ] **Step 1: Write real Quart endpoint tests**

Use the existing Quart test client fixture to execute list, create/update, delete, and effective-policy requests. Assert response status and JSON for valid private IDs, whitespace normalization, missing IDs, invalid boolean bodies, conflicting `group_id` plus `user_id` query parameters, unavailable service state, save rollback, and group-route regression.

- [ ] **Step 2: Run the API tests and confirm failure**

Run: `python -m pytest -q tests/test_plugin_management_api.py`

Expected: new private routes return 404 or fail their new validation assertions.

- [ ] **Step 3: Implement the private CRUD routes**

Mirror the current group response envelope and error mapping. Parse JSON objects only, normalize `user_id`, validate both flags as JSON booleans, return 400 for client input errors, 503 when the policy service is unavailable, and preserve the current server-error contract for transactional save failures.

- [ ] **Step 4: Extend effective-policy lookup**

Accept `user_id` on `GET content-safety`. Return 400 when both IDs are present. Route a group ID only to group lookup and a user ID only to private lookup; an omitted identity returns strict defaults under the existing envelope.

- [ ] **Step 5: Run and commit the API slice**

Run: `python -m pytest -q tests/test_plugin_management_api.py`

Expected: all endpoint tests pass through the Quart client.

Commit: `feat: expose private safety policy management api`

---

### Task 4: Extract executable session-policy UI state

**Files:**
- Create: `pages/pluginCenter/policy-state.mjs`
- Create: `tests/js/policy-state.test.mjs`
- Modify: `pages/pluginCenter/app.js`

**Interfaces:**
- Produces: `POLICY_SCOPES`, `createPolicyBucket`, `policyRecordId`, `hasUnsavedPolicyDraft`, `selectPolicyRecord`, `replacePolicyRecords`, `upsertPolicyRecord`, `removePolicyRecord`, and `discardPolicyDraft`.
- Each bucket owns `records`, `selectedId`, `draft`, `baseline`, `search`, `loading`, `saving`, and `error`.

- [ ] **Step 1: Write failing Node state tests**

Cover independent group/private buckets, normalized record IDs, dirty detection after either toggle changes, clean state after save replacement, deletion clearing only the active scope, scope switching without cross-contamination, and discard restoring the saved baseline. Import the real module from the test; do not duplicate its logic in the test.

- [ ] **Step 2: Run the Node tests and confirm module absence**

Run: `node --test tests/js/policy-state.test.mjs`

Expected: failure because `policy-state.mjs` does not yet exist.

- [ ] **Step 3: Implement immutable state helpers**

Export the named functions. Return new arrays/objects from replacements and mutations, use `group_id` for group records and `user_id` for private records, preserve saved timestamps from API records, and compare only identifier plus the two booleans for dirty status.

- [ ] **Step 4: Integrate the helpers into app state**

Import the module from `app.js`, replace the single group-policy state with `policyState.activeScope`, `policyState.group`, and `policyState.private`, and make render and request code use the active bucket without sharing mutable arrays or drafts.

- [ ] **Step 5: Run and commit the state slice**

Run: `node --test tests/js/policy-state.test.mjs`

Run: `node --check pages/pluginCenter/policy-state.mjs`

Run: `node --check pages/pluginCenter/app.js`

Expected: all commands exit 0.

Commit: `refactor: isolate session policy ui state`

---

### Task 5: Build the Sakura-aligned session-policy manager

**Files:**
- Modify: `pages/pluginCenter/index.html`
- Modify: `pages/pluginCenter/app.js`
- Modify: `pages/pluginCenter/styles.css`
- Modify: `tests/test_plugin_center_frontend.py`

**Interfaces:**
- Consumes: state helpers from Task 4 and group/private routes from Task 3.
- Produces in `app.js`: `activePolicyDefinition()`, `activePolicyBucket()`, `renderPolicyManager()`, `reloadPolicies(scope)`, `requestPolicyScopeChange(scope)`, `requestPolicySelection(id)`, `confirmPolicyDraftDiscard()`, `addPolicy(id)`, `savePolicy()`, and `deletePolicy()`.

- [ ] **Step 1: Write failing frontend contract tests**

Parse the HTML and assert the “会话策略” navigation label, an accessible two-button segmented control, catalog/search/add/count regions, editor metadata, two labeled switch cards, save/delete actions, empty/loading/error hooks, and the add dialog's scope-sensitive label. Extract each named JavaScript function body and assert it calls the appropriate group/private URL, dirty-confirm flow, state helper, and render path. Assert CSS contains selectors using existing Sakura variables plus media queries at `900px` and `620px`.

- [ ] **Step 2: Run the frontend tests and confirm failure**

Run: `python -m pytest -q tests/test_plugin_center_frontend.py`

Expected: new semantic structure and function-body assertions fail against the group-only page.

- [ ] **Step 3: Replace the compressed group-only markup**

Rename the page to “会话策略”. Add `role="tablist"` scope buttons with `aria-selected`, a structured two-column manager, searchable catalog, add action, record count, status badges, editor metadata, switch cards, and explicit loading/empty/error/status elements. Keep stable IDs where useful for compatibility and give new controls unambiguous IDs.

- [ ] **Step 4: Implement scope-aware orchestration**

Map group scope to the existing group endpoints and `group_id`, and private scope to the new private endpoints and `user_id`. Before changing active scope or selected record, call `hasUnsavedPolicyDraft`; show the existing global confirmation dialog and continue only after confirmation. Disable controls while loading/saving, render API errors in the page, update counts and saved time after save, and return to strict empty editor state after delete.

- [ ] **Step 5: Apply the Sakura visual system**

Use `--surface`, `--border`, `--primary-soft`, `--secondary-soft`, `--safe-soft`, `--danger-soft`, `--radius*`, and `--shadow*`. Give the segmented control, catalog rows, textual status badges, editor cards, switch focus rings, primary save, and danger delete the same spacing, typography, radii, and motion language as the rest of the plugin center. At `max-width: 900px`, stack catalog and editor; at `max-width: 620px`, tighten padding and make action controls full-width where appropriate.

- [ ] **Step 6: Run all frontend checks and commit**

Run: `python -m pytest -q tests/test_plugin_center_frontend.py`

Run: `node --test tests/js/policy-state.test.mjs`

Run: `node --check pages/pluginCenter/app.js`

Expected: all checks pass.

Commit: `feat: redesign session policy management ui`

---

### Task 6: Document and verify the complete feature

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/project/configuration.md`
- Modify: `docs/project/architecture.md`
- Modify: `metadata.yaml`

**Interfaces:**
- Documents: strict private defaults, per-user management, group/private precedence, API routes, cache isolation, and the unified session-policy UI.

- [ ] **Step 1: Update user and architecture documentation**

Describe how administrators add/delete group IDs and user IDs, what both switches mean, that deletion restores strict defaults, and that group messages never consult private records. Add the three private routes and the `user_id` effective-policy query. Record that cache identity includes the scope and selected ID. Keep metadata version at `v3.6.1` and only refresh descriptive feature text if the file carries such text.

- [ ] **Step 2: Run focused integration checks**

Run: `python -m pytest -q tests/test_group_safety_config.py tests/test_filtering.py tests/test_plugin_management_api.py tests/test_plugin_center_frontend.py tests/test_checkin_calendar.py`

Run: `node --test tests/js/policy-state.test.mjs`

Run: `node --check pages/pluginCenter/policy-state.mjs`

Run: `node --check pages/pluginCenter/app.js`

Run: `python -m json.tool _conf_schema.json > $null`

Expected: every command exits 0 with no failed tests.

- [ ] **Step 3: Run full regression and repository checks**

Run: `python -m pytest -q tests --basetemp="D:\Documents\杂项\.pytest-session-policy-final"`

Run: `git diff --check`

Run: `git diff --check fork/master...HEAD`

Expected: full suite passes and both diff checks produce no errors.

- [ ] **Step 4: Perform browser visual QA**

Open the plugin center and inspect the group and private scopes at viewport widths 1440 px, 900 px, and 620 px. Exercise add, search, select, toggle, dirty switch confirmation, save, delete confirmation, loading, empty, and error states. Confirm keyboard focus is visible and no horizontal overflow or clipped dialog is present.

- [ ] **Step 5: Commit documentation and final fixes**

Commit: `docs: document session policy management`

- [ ] **Step 6: Prepare publication evidence**

Record final commit SHA, focused and full test counts, Node check results, visual-QA widths, `git status --short`, and `git diff --stat fork/master...HEAD`. Push only after the mandatory Tier 3 verification reports `VERIFIED`, then compare the remote branch SHA with local HEAD.

---

## Acceptance Criteria

1. The AstrBot native configuration page persistently manages separate add/delete template lists for group IDs and private user IDs.
2. Group messages use group policy only; private messages use sender user policy only; all missing, malformed, deleted, or failed private lookups are strict.
3. Cache entries are isolated across users and between group/private scopes, including identical numeric IDs.
4. All existing group routes remain compatible and the three new private routes work through real Quart requests.
5. The unified “会话策略” page provides isolated group/private catalogs and drafts, dirty-draft confirmation, searchable persistent records, save/delete workflows, and meaningful loading/empty/error feedback.
6. The UI matches existing Sakura tokens and remains usable at 1440 px, 900 px, and 620 px with visible keyboard focus.
7. Focused tests, Node behavior tests, syntax checks, JSON validation, the full pytest suite, and both diff checks pass from fresh runs.
8. The verified branch is pushed to the personal fork and the remote SHA equals local HEAD.
