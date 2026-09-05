# Group Policy Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build persistent, add/edit/delete group-policy managers in AstrBot's plugin configuration page and the plugin WebUI, using plugin configuration as the single source of truth while preserving existing SQLite policies during upgrade.

**Architecture:** Add a focused `GroupSafetyService` that owns validation, immutable runtime snapshots, config persistence, rollback, and one-time SQLite import. The runtime filter and Web API consume that service; AstrBot's native `template_list` and the custom WebUI edit the same `AstrBotConfig` list.

**Tech Stack:** Python 3.10+, asyncio, AstrBot `AstrBotConfig`, Quart plugin Web API, SQLite legacy reader, vanilla HTML/CSS/JavaScript, pytest.

## Global Constraints

- AstrBot minimum version remains `>=4.16`; add no dependency.
- `group_content_safety_policies` is the only post-migration authority.
- Unconfigured groups and private chats always enable both strict switches.
- Explicit `{true, true}` entries remain visible until the user deletes them.
- Custom safety terms and Pixiv illustration blacklist behavior do not change.
- Existing `GET content-safety?group_id=` and `POST content-safety/group-policy` remain compatible.
- Preserve existing untracked `.pytest-tmp*` directories and exclude them from commits.

---

### Task 1: Configuration-backed group safety service

**Files:**
- Create: `group_safety.py`
- Modify: `_conf_schema.json`
- Test: `tests/test_group_safety_config.py`

**Interfaces:**
- Produces: `normalize_group_id(value: object) -> str`
- Produces: `normalize_policy_entries(raw: object) -> tuple[list[dict[str, object]], list[str]]`
- Produces: `GroupSafetyService.initialize(legacy_store)`, `list_policies()`, `get_policy()`, `upsert_policy()`, and `remove_policy(group_id: object) -> tuple[bool, dict[str, object]]`.

- [ ] **Step 1: Add failing schema and normalization tests**

Create assertions equivalent to:

```python
def test_group_policy_schema_is_editable_template_list():
    schema = json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))
    field = schema["group_content_safety_policies"]
    template = field["templates"]["group_policy"]
    assert field["type"] == "template_list"
    assert field["default"] == []
    assert template["display_item"] == "group_id"
    assert set(template["items"]) == {
        "group_id", "general_only_enabled", "builtin_terms_enabled"
    }

def test_normalize_entries_keeps_first_valid_duplicate_and_explicit_strict():
    entries, warnings = normalize_policy_entries([
        {"__template_key": "group_policy", "group_id": " 100 ",
         "general_only_enabled": True, "builtin_terms_enabled": True},
        {"__template_key": "group_policy", "group_id": "100",
         "general_only_enabled": False, "builtin_terms_enabled": False},
    ])
    assert [item["group_id"] for item in entries] == ["100"]
    assert entries[0]["general_only_enabled"] is True
    assert warnings
```

- [ ] **Step 2: Verify the new tests fail**

Run: `python -m pytest -q tests/test_group_safety_config.py`

Expected: FAIL because `group_safety.py` and the schema fields do not exist.

- [ ] **Step 3: Define the native plugin configuration window**

Add these top-level schema entries without changing existing settings:

```json
"group_content_safety_policies": {
  "type": "template_list",
  "description": "群策略配置",
  "hint": "按群独立管理普通分级和内置安全词；删除条目后恢复默认严格策略。",
  "default": [],
  "templates": {
    "group_policy": {
      "name": "群策略",
      "display_item": "group_id",
      "hide_hint_in_list": true,
      "items": {
        "group_id": {"description": "群 ID", "type": "string", "default": ""},
        "general_only_enabled": {"description": "强制普通分级", "type": "bool", "default": true},
        "builtin_terms_enabled": {"description": "启用内置安全词", "type": "bool", "default": true}
      }
    }
  }
},
"group_content_safety_policies_migrated": {
  "type": "bool",
  "description": "群策略迁移标记",
  "default": false,
  "invisible": true
}
```

- [ ] **Step 4: Implement validation and runtime snapshots**

Implement these constants and public shapes in `group_safety.py`:

```python
CONFIG_KEY = "group_content_safety_policies"
MIGRATION_KEY = "group_content_safety_policies_migrated"
TEMPLATE_KEY = "group_policy"
MAX_GROUP_ID_LENGTH = 128

def strict_policy(group_id: str) -> dict[str, object]:
    return {
        "group_id": group_id,
        "general_only_enabled": True,
        "builtin_terms_enabled": True,
        "updated_by": "",
        "updated_at": "",
        "is_default": True,
    }
```

`normalize_policy_entries()` must accept only a list, validate true `bool` values, trim IDs, reject control characters, keep the first valid duplicate, attach `__template_key`, and return warnings containing the rejected entry index. `GroupSafetyService` must use one `asyncio.Lock`, return copied dictionaries, and sort lists by `group_id`. Runtime response metadata may contain `updated_by` and `updated_at`, but only the three user-editable fields are persisted in the authoritative template list.

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m json.tool _conf_schema.json > $null; python -m pytest -q tests/test_group_safety_config.py`

Expected: PASS.

Commit:

```powershell
git add _conf_schema.json group_safety.py tests/test_group_safety_config.py
git commit -m "feat: add configuration-backed group policies"
```

---

### Task 2: One-time SQLite migration and runtime integration

**Files:**
- Modify: `checkin/group_safety_store.py`
- Modify: `main.py`
- Modify: `pixiv/filters.py`
- Modify: `tests/test_checkin_group_safety.py`
- Modify: `tests/test_filtering.py`

**Interfaces:**
- Consumes: `GroupSafetyService` from Task 1.
- Produces: `CheckinStore.list_group_content_safety_records() -> list[dict[str, object]]` as a legacy-only reader.
- Produces: initialized `GetPxPlugin.group_safety_service` before Web API registration.

- [ ] **Step 1: Add failing migration and filter tests**

Cover these exact state transitions:

```python
@pytest.mark.asyncio
async def test_initialize_imports_legacy_rows_once(config, legacy_store):
    config["group_content_safety_policies"] = []
    config["group_content_safety_policies_migrated"] = False
    legacy_store.rows = [{"group_id": "200", "general_only_enabled": False,
                          "builtin_terms_enabled": True,
                          "updated_by": "old", "updated_at": "2026-09-04T00:00:00+08:00"}]
    service = GroupSafetyService(config, log_prefix="[GetPx]")
    await service.initialize(legacy_store)
    assert config["group_content_safety_policies_migrated"] is True
    assert (await service.get_policy("200"))["general_only_enabled"] is False

@pytest.mark.asyncio
async def test_empty_migrated_config_never_reimports_legacy(config, legacy_store):
    config["group_content_safety_policies"] = []
    config["group_content_safety_policies_migrated"] = True
    await GroupSafetyService(config, log_prefix="[GetPx]").initialize(legacy_store)
    assert config["group_content_safety_policies"] == []
```

Also assert a failed `save_config()` restores both config keys, leaves migration false, and exposes strict defaults for that initialization attempt. Update filter fixtures so `_content_safety_policy()` reads `plugin.group_safety_service`, while absent service, exception, missing group, and private chat all return `STRICT_CONTENT_SAFETY_POLICY`.

- [ ] **Step 2: Verify migration tests fail**

Run: `python -m pytest -q tests/test_checkin_group_safety.py tests/test_filtering.py`

Expected: FAIL on the missing legacy list method and old filter dependency.

- [ ] **Step 3: Add the legacy SQLite list reader**

Add an async wrapper and sync query to `GroupSafetyStoreMixin`:

```python
async def list_group_content_safety_records(self) -> list[dict[str, object]]:
    async with self._lock:
        return await asyncio.to_thread(self._list_group_content_safety_records_sync)

def _list_group_content_safety_records_sync(self) -> list[dict[str, object]]:
    with closing(self._connect()) as conn:
        rows = conn.execute(
            "SELECT group_id, general_only_enabled, builtin_terms_enabled, "
            "updated_by, updated_at FROM group_content_safety ORDER BY group_id"
        ).fetchall()
    return [{"group_id": str(row["group_id"]),
             "general_only_enabled": bool(row["general_only_enabled"]),
             "builtin_terms_enabled": bool(row["builtin_terms_enabled"]),
             "updated_by": str(row["updated_by"] or ""),
             "updated_at": str(row["updated_at"] or "")} for row in rows]
```

Import `normalize_group_id` from the new module with package/direct-test compatibility and remove its duplicate definition from this file.

- [ ] **Step 4: Implement migration and wire the service**

`GroupSafetyService.initialize()` must implement:

```python
if migrated:
    install(normalized_config)
elif normalized_config:
    persist(normalized_config, migrated=True)
else:
    legacy = await legacy_store.list_group_content_safety_records()
    persist(normalize_policy_entries(legacy)[0], migrated=True)
```

The persist helper must snapshot both original config values, write both candidate values, call `save_config()`, restore originals on exception, and install the new runtime mapping only after success.

In `GetPxPlugin.__init__`, initialize `self.group_safety_service = GroupSafetyService(config, log_prefix=LOG_PREFIX)`. In `initialize()`, call `await self.group_safety_service.initialize(self.checkin_store)` after `CheckinStore` creation and before `plugin_web_api.register()`.

In `FiltersMixin._content_safety_policy`, replace `checkin_store` lookup with:

```python
service = getattr(self, "group_safety_service", None)
if not group_id or service is None:
    return STRICT_CONTENT_SAFETY_POLICY
value = await service.get_policy(group_id)
```

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest -q tests/test_group_safety_config.py tests/test_checkin_group_safety.py tests/test_filtering.py`

Expected: PASS.

Commit:

```powershell
git add group_safety.py checkin/group_safety_store.py main.py pixiv/filters.py tests/test_checkin_group_safety.py tests/test_filtering.py
git commit -m "feat: migrate group policies into plugin configuration"
```

---

### Task 3: Transactional management API

**Files:**
- Modify: `group_safety.py`
- Modify: `plugin_api/api.py`
- Modify: `tests/test_plugin_management_api.py`

**Interfaces:**
- Consumes: initialized `plugin.group_safety_service`.
- Produces: `GET content-safety/group-policies`.
- Produces: `POST content-safety/group-policy/remove`.
- Preserves: current single-policy GET and POST response shapes.

- [ ] **Step 1: Add failing CRUD and rollback tests**

Add cases that assert:

```python
response = await client.get("/content-safety/group-policies")
assert response.json["group_policies"] == sorted(
    response.json["group_policies"], key=lambda item: item["group_id"])

response = await client.post("/content-safety/group-policy/remove",
                             json={"group_id": "300"})
assert response.json["removed"] is True
assert response.json["group_policy"]["is_default"] is True
assert response.json["group_policy"]["general_only_enabled"] is True
assert response.json["group_policy"]["builtin_terms_enabled"] is True
```

Also cover idempotent removal (`removed=False`), explicit strict upsert remaining in the list, duplicate upsert updating one row, invalid IDs, non-boolean switches, service missing as 503, and `save_config()` failure preserving the previous list and GET result.

- [ ] **Step 2: Verify API tests fail**

Run: `python -m pytest -q tests/test_plugin_management_api.py`

Expected: FAIL because list/remove routes are missing and existing routes use SQLite.

- [ ] **Step 3: Implement transactional service writes**

For upsert and remove, build a candidate mapping under the service lock, serialize stable entries as:

```python
{"__template_key": TEMPLATE_KEY,
 "group_id": group_id,
 "general_only_enabled": general_only_enabled,
 "builtin_terms_enabled": builtin_terms_enabled}
```

Set `MIGRATION_KEY=True` on every successful CRUD. If `save_config()` raises, restore the original list and marker in place and retain the previous runtime mapping. `remove_policy()` returns exactly `(removed: bool, strict_default_policy: dict[str, object])` for the API.

- [ ] **Step 4: Register and implement API routes**

Add route registrations:

```python
("content-safety/group-policies", self.content_safety_group_policies,
 ["GET"], "List group content safety policies"),
("content-safety/group-policy/remove", self.content_safety_group_policy_remove,
 ["POST"], "Remove a group content safety policy"),
```

All group-policy endpoints must check `group_safety_service`, return validation errors as 400, missing service as 503, and unexpected persistence errors through `internal_error()`. Keep custom terms and content-safety metadata unchanged.

- [ ] **Step 5: Run API tests and commit**

Run: `python -m pytest -q tests/test_plugin_management_api.py`

Expected: PASS.

Commit:

```powershell
git add group_safety.py plugin_api/api.py tests/test_plugin_management_api.py
git commit -m "feat: add persistent group policy management API"
```

---

### Task 4: Dedicated WebUI group-policy manager

**Files:**
- Modify: `pages/pluginCenter/index.html`
- Modify: `pages/pluginCenter/app.js`
- Modify: `pages/pluginCenter/styles.css`
- Modify: `tests/test_plugin_center_frontend.py`

**Interfaces:**
- Consumes: list/upsert/remove endpoints from Task 3.
- Produces: independent `data-view="policies"` workspace with persistent list, add dialog, editor, and deletion confirmation.

- [ ] **Step 1: Add failing frontend contract tests**

Assert the static assets contain:

```python
assert 'data-view="policies"' in html
assert 'id="policiesView"' in html
assert 'id="policyAddDialog"' in html
assert 'id="policyList"' in html
assert 'id="policySearch"' in html
assert 'content-safety/group-policies' in script
assert 'content-safety/group-policy/remove' in script
assert 'safetyGroupInput' not in html
assert '删除后恢复默认严格策略' in html + script
assert '@media (max-width: 900px)' in css
```

- [ ] **Step 2: Verify frontend tests fail**

Run: `python -m pytest -q tests/test_plugin_center_frontend.py`

Expected: FAIL on the missing independent page and old manual input.

- [ ] **Step 3: Build the independent page markup and styles**

Move group-policy management out of `safetyView`. Add a navigation button labelled `群策略配置`, a `policiesView` two-column workspace, list search/count/empty state, editor switches, save/delete buttons, and an add-group `<dialog>`. Use `aria-live` for loading/error status and retain the existing shared confirmation dialog for deletion.

Desktop uses a bounded left list and flexible right editor. At `max-width: 900px`, switch to one column; at `max-width: 620px`, allow navigation and actions to wrap. Preserve visible `:focus-visible` treatment.

- [ ] **Step 4: Replace single-input state with persistent-list state**

Use one server snapshot plus draft state:

```javascript
groupPolicies: [],
selectedPolicyGroupId: "",
policyQuery: "",
policyDraft: null,
policyLoading: false,
policySaving: false,
policyDeleting: false,
```

`reloadAll()` must request `content-safety/group-policies` independently from `checkin-groups`. Rendering filters only for display and never mutates `groupPolicies`. Add dialog submission rejects a local duplicate by selecting the existing item. Save updates the snapshot only from the successful response. Save failure restores the selected server record. Delete success removes the record, selects the next neighbor, or focuses the add button when empty; delete failure retains list and selection.

- [ ] **Step 5: Run frontend and API tests and commit**

Run: `python -m pytest -q tests/test_plugin_center_frontend.py tests/test_plugin_management_api.py`

Expected: PASS.

Commit:

```powershell
git add pages/pluginCenter/index.html pages/pluginCenter/app.js pages/pluginCenter/styles.css tests/test_plugin_center_frontend.py
git commit -m "feat: add group policy management workspace"
```

---

### Task 5: Documentation, regression verification, and publication

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `metadata.yaml` only if the release version is intentionally incremented in the same change.

**Interfaces:**
- Documents: both management interfaces, migration behavior, deletion semantics, and shared persistence.

- [ ] **Step 1: Update user-facing documentation**

Replace the statement that group policy is stored in the check-in SQLite database with the following behavior:

```text
“群策略配置”可在 AstrBot 插件配置页和插件管理中心中管理；两处共用同一份持久化配置。删除群后，该群恢复“强制普通分级”和“内置安全词”均开启的默认策略。升级时会一次性导入旧 SQLite 策略。
```

Add the same concise behavior to the current unreleased changelog section.

- [ ] **Step 2: Run all required checks**

Run:

```powershell
python -m json.tool _conf_schema.json > $null
python -m pytest -q tests/test_group_safety_config.py tests/test_checkin_group_safety.py tests/test_filtering.py
python -m pytest -q tests/test_plugin_management_api.py
python -m pytest -q tests/test_plugin_center_frontend.py
python -m pytest -q
git diff --check
```

Expected: every command exits 0 and the full suite reports no failure.

- [ ] **Step 3: Inspect the bounded final diff**

Run:

```powershell
git status --short
git diff --stat fork/master...HEAD
git diff --name-only fork/master...HEAD
```

Expected: only the planned source, test, documentation, design, and plan files appear; `.pytest-tmp*` directories remain untracked and excluded.

- [ ] **Step 4: Commit documentation and push normally**

```powershell
git add README.md CHANGELOG.md
git commit -m "docs: explain persistent group policy management"
git push fork HEAD:master
```

Expected: `fork/master` advances by normal fast-forward; no force push and no pull request creation.

- [ ] **Step 5: Verify the remote commit**

Run:

```powershell
$local = git rev-parse HEAD
$remote = git ls-remote fork refs/heads/master | ForEach-Object { ($_ -split "`t")[0] }
if ($local -ne $remote) { throw "fork/master does not match local HEAD" }
```

Expected: no exception; local `HEAD` and `fork/master` are identical.
