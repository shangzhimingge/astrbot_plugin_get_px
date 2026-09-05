import pytest

from group_safety import CONFIG_KEY, MIGRATION_KEY, GroupSafetyService, normalize_policy_entries

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
    assert messages
    assert await service.list_policies() == []
    assert config[MIGRATION_KEY] is True

@pytest.mark.asyncio
async def test_initialize_legacy_read_failure_logs_and_keeps_strict(monkeypatch):
    messages = []
    monkeypatch.setattr("group_safety.logger.warning", messages.append)
    config = Config({CONFIG_KEY: [], MIGRATION_KEY: False})
    service = GroupSafetyService(config)
    await service.initialize(TrackingLegacy(error=RuntimeError("broken")))
    assert messages
    assert config[MIGRATION_KEY] is False
    assert (await service.get_policy("200"))["is_default"] is True
    assert await service.list_policies() == []

@pytest.mark.asyncio
async def test_initialize_fail_once_rolls_back_then_retries_incremental(monkeypatch):
    messages = []
    monkeypatch.setattr("group_safety.logger.warning", messages.append)
    config = FailOnceConfig({CONFIG_KEY: [], MIGRATION_KEY: False})
    service = GroupSafetyService(config)
    legacy = TrackingLegacy([{"group_id": "200", "general_only_enabled": False, "builtin_terms_enabled": True}])
    await service.initialize(legacy)
    assert legacy.calls == 1
    assert config[CONFIG_KEY] == [] and config[MIGRATION_KEY] is False
    assert (await service.get_policy("200"))["is_default"] is True
    assert messages
    legacy.records.append({"group_id": "100", "general_only_enabled": True, "builtin_terms_enabled": False})
    await service.initialize(legacy)
    assert legacy.calls == 2
    assert config[MIGRATION_KEY] is True
    assert [p["group_id"] for p in await service.list_policies()] == ["100", "200"]

def test_explicit_strict_is_retained():
    entries, _ = normalize_policy_entries([{"group_id": "1", "general_only_enabled": True, "builtin_terms_enabled": True}])
    assert entries[0]["general_only_enabled"] is True
