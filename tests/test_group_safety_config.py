import pytest

from copy import deepcopy

from group_safety import (
    CONFIG_KEY,
    MIGRATION_KEY,
    PRIVATE_CONFIG_KEY,
    GroupSafetyService,
    normalize_policy_entries,
)

class Config(dict):
    def save_config(self):
        if self.get("fail"):
            raise RuntimeError("save failed")

class TrackingLegacy:
    def __init__(self, records=None, error=None):
        self.records = records or []
        self.error = error
        self.calls = 0
    async def list_group_content_safety_records(self):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.records)

class FailOnceConfig(Config):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.failures = 1
    def save_config(self):
        if self.failures:
            self.failures -= 1
            raise RuntimeError("save failed")

def test_normalize_entries_deduplicates_and_warns():
    entries, warnings = normalize_policy_entries([
        {"group_id": " 100 ", "general_only_enabled": True, "builtin_terms_enabled": True},
        {"group_id": "100", "general_only_enabled": False, "builtin_terms_enabled": False},
    ])
    assert entries[0]["group_id"] == "100"
    assert entries[0]["general_only_enabled"] is True
    assert warnings

@pytest.mark.asyncio
async def test_initialize_invalid_nonempty_config_skips_legacy_and_logs(monkeypatch):
    messages = []
    monkeypatch.setattr("group_safety.logger.warning", messages.append)
    config = Config({CONFIG_KEY: [{"group_id": "", "general_only_enabled": True, "builtin_terms_enabled": True}], MIGRATION_KEY: False})
    legacy = TrackingLegacy([{"group_id": "200", "general_only_enabled": False, "builtin_terms_enabled": True}])
    service = GroupSafetyService(config)
    await service.initialize(legacy)
    assert legacy.calls == 0
    assert any("config" in msg and "entry 0" in msg and "group_id is required" in msg for msg in messages)
    assert await service.list_policies() == []
    assert config[MIGRATION_KEY] is True

@pytest.mark.parametrize("raw", [{"group_id": "200"}, "invalid", None])
@pytest.mark.asyncio
async def test_initialize_nonlist_config_is_config_first(raw, monkeypatch):
    messages = []
    monkeypatch.setattr("group_safety.logger.warning", messages.append)
    config = Config({CONFIG_KEY: raw, MIGRATION_KEY: False})
    legacy = TrackingLegacy([{"group_id": "200", "general_only_enabled": False, "builtin_terms_enabled": True}])
    service = GroupSafetyService(config)
    await service.initialize(legacy)
    assert legacy.calls == 0
    assert any("config" in msg for msg in messages)
    assert (await service.get_policy("200"))["is_default"] is True
    assert config[MIGRATION_KEY] is True

@pytest.mark.asyncio
async def test_initialize_legacy_read_failure_logs_and_keeps_strict(monkeypatch):
    messages = []
    monkeypatch.setattr("group_safety.logger.warning", messages.append)
    config = Config({CONFIG_KEY: [], MIGRATION_KEY: False})
    service = GroupSafetyService(config)
    await service.initialize(TrackingLegacy(error=RuntimeError("broken")))
    assert any("legacy: read failed error_type=RuntimeError" in msg for msg in messages)
    assert config[MIGRATION_KEY] is False
    assert (await service.get_policy("200"))["is_default"] is True
    assert (await service.get_policy("200"))["general_only_enabled"] is True
    assert (await service.get_policy("200"))["builtin_terms_enabled"] is True
    assert await service.list_policies() == []

@pytest.mark.asyncio
async def test_initialize_fail_once_rolls_back_then_retries_incremental(monkeypatch):
    messages = []
    monkeypatch.setattr("group_safety.logger.warning", messages.append)
    config = FailOnceConfig({CONFIG_KEY: [], MIGRATION_KEY: False})
    service = GroupSafetyService(config)
    legacy = TrackingLegacy([
        {"group_id": "200", "general_only_enabled": False, "builtin_terms_enabled": True},
        {"group_id": "100", "general_only_enabled": True, "builtin_terms_enabled": False},
    ])
    await service.initialize(legacy)
    assert legacy.calls == 1
    assert config[CONFIG_KEY] == [] and config[MIGRATION_KEY] is False
    first_policy = await service.get_policy("200")
    assert first_policy["general_only_enabled"] is True
    assert first_policy["builtin_terms_enabled"] is True
    assert first_policy["is_default"] is True
    assert any("legacy: save failed error_type=RuntimeError" in msg for msg in messages)
    await service.initialize(legacy)
    assert legacy.calls == 2
    assert config[MIGRATION_KEY] is True
    policies = await service.list_policies()
    assert [(p["group_id"], p["general_only_enabled"], p["builtin_terms_enabled"], p["is_default"]) for p in policies] == [("100", True, False, False), ("200", False, True, False)]
    assert config[CONFIG_KEY] == [
        {"__template_key": "group_policy", "group_id": "100", "general_only_enabled": True, "builtin_terms_enabled": False, "updated_by": "", "updated_at": ""},
        {"__template_key": "group_policy", "group_id": "200", "general_only_enabled": False, "builtin_terms_enabled": True, "updated_by": "", "updated_at": ""},
    ]

def test_explicit_strict_is_retained():
    entries, _ = normalize_policy_entries([{"group_id": "1", "general_only_enabled": True, "builtin_terms_enabled": True}])
    assert entries[0]["general_only_enabled"] is True

@pytest.mark.asyncio
async def test_private_policy_namespace_isolated_from_group():
    config = Config({CONFIG_KEY: [], MIGRATION_KEY: False, PRIVATE_CONFIG_KEY: []})
    service = GroupSafetyService(config)
    await service.upsert_private_policy(
        "u1", general_only_enabled=False, builtin_terms_enabled=True
    )
    assert (await service.get_private_policy("u1"))["general_only_enabled"] is False
    assert (await service.get_policy("u1"))["is_default"] is True
    assert config[MIGRATION_KEY] is False
    assert config[CONFIG_KEY] == []


@pytest.mark.asyncio
async def test_private_initialize_survives_group_legacy_read_failure():
    config = Config(
        {
            CONFIG_KEY: [],
            MIGRATION_KEY: False,
            PRIVATE_CONFIG_KEY: [
                {
                    "__template_key": "private_policy",
                    "user_id": "u1",
                    "general_only_enabled": False,
                    "builtin_terms_enabled": True,
                    "updated_at": "2026-09-06T00:00:00+00:00",
                    "updated_by": "web",
                }
            ],
        }
    )
    service = GroupSafetyService(config)
    await service.initialize(TrackingLegacy(error=RuntimeError("broken")))
    policy = await service.get_private_policy("u1")
    assert policy["is_default"] is False
    assert policy["general_only_enabled"] is False
    assert policy["updated_by"] == "web"


@pytest.mark.asyncio
async def test_scope_writes_do_not_touch_other_scope_or_migration_marker():
    config = Config(
        {
            CONFIG_KEY: [{"__template_key": "group_policy", "group_id": "g1", "general_only_enabled": True, "builtin_terms_enabled": False}],
            MIGRATION_KEY: False,
            PRIVATE_CONFIG_KEY: [{"__template_key": "private_policy", "user_id": "u1", "general_only_enabled": False, "builtin_terms_enabled": True}],
        }
    )
    service = GroupSafetyService(config)
    service._install(config[CONFIG_KEY])
    service._install(config[PRIVATE_CONFIG_KEY], private=True)
    group_before = deepcopy(config[CONFIG_KEY])
    private_list = config[PRIVATE_CONFIG_KEY]
    await service.upsert_private_policy("u2", general_only_enabled=False, builtin_terms_enabled=False)
    assert config[CONFIG_KEY] == group_before
    assert config[MIGRATION_KEY] is False
    assert config[PRIVATE_CONFIG_KEY] is private_list
    private_before = deepcopy(config[PRIVATE_CONFIG_KEY])
    await service.upsert_group_policy("g2", general_only_enabled=False, builtin_terms_enabled=True)
    assert config[PRIVATE_CONFIG_KEY] == private_before


@pytest.mark.asyncio
async def test_failed_scope_write_rolls_back_config_and_runtime():
    config = Config({CONFIG_KEY: [], MIGRATION_KEY: True, PRIVATE_CONFIG_KEY: []})
    service = GroupSafetyService(config)
    await service.upsert_private_policy("u1", general_only_enabled=False, builtin_terms_enabled=True)
    before_config = deepcopy(dict(config))
    before_private = await service.list_private_policies()
    config["fail"] = True
    with pytest.raises(RuntimeError, match="save failed"):
        await service.upsert_group_policy("g1", general_only_enabled=False, builtin_terms_enabled=False)
    assert {key: value for key, value in config.items() if key != "fail"} == before_config
    assert await service.list_private_policies() == before_private
    assert await service.list_group_policies() == []


@pytest.mark.asyncio
async def test_group_and_private_metadata_survive_reinitialize():
    config = Config({CONFIG_KEY: [], MIGRATION_KEY: True, PRIVATE_CONFIG_KEY: []})
    service = GroupSafetyService(config)
    await service.upsert_group_policy("g1", general_only_enabled=False, builtin_terms_enabled=True, updated_by="web")
    await service.upsert_private_policy("u1", general_only_enabled=True, builtin_terms_enabled=False, updated_by="web")
    reloaded = GroupSafetyService(config)
    await reloaded.initialize(TrackingLegacy())
    group = await reloaded.get_group_policy("g1")
    private = await reloaded.get_private_policy("u1")
    assert group["updated_by"] == private["updated_by"] == "web"
    assert group["updated_at"] and private["updated_at"]
