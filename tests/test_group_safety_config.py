import pytest
from group_safety import GroupSafetyService, normalize_policy_entries

class Config(dict):
    def save_config(self):
        if self.get("fail"): raise RuntimeError("save failed")

class Legacy:
    async def list_group_content_safety_records(self):
        return [{"group_id":"200","general_only_enabled":False,"builtin_terms_enabled":True}]

class TrackingLegacy(Legacy):
    calls = 0
    async def list_group_content_safety_records(self): self.calls += 1; return await super().list_group_content_safety_records()

class FailOnceConfig(Config):
    failures = 1
    def save_config(self):
        if self.failures: self.failures -= 1; raise RuntimeError("save failed")

def test_normalize_entries_deduplicates_and_warns():
    entries, warnings = normalize_policy_entries([{"group_id":" 100 ","general_only_enabled":True,"builtin_terms_enabled":True},{"group_id":"100","general_only_enabled":False,"builtin_terms_enabled":False}])
    assert entries[0]["group_id"] == "100" and entries[0]["general_only_enabled"] is True and warnings

@pytest.mark.asyncio
async def test_migration_and_empty_after_migration():
    c=Config(group_content_safety_policies=[], group_content_safety_policies_migrated=False); s=GroupSafetyService(c); await s.initialize(Legacy()); assert (await s.get_policy("200"))["general_only_enabled"] is False
    c["group_content_safety_policies"]=[]; await s.initialize(Legacy()); assert await s.list_policies() == []

@pytest.mark.asyncio
async def test_failed_save_rolls_back():
    c=Config(group_content_safety_policies=[], group_content_safety_policies_migrated=True, fail=True); s=GroupSafetyService(c); await s.initialize(Legacy())
    with pytest.raises(RuntimeError): await s.upsert_policy("3", general_only_enabled=False, builtin_terms_enabled=True)
    assert await s.list_policies() == []

@pytest.mark.asyncio
async def test_nonempty_invalid_config_does_not_read_legacy():
    c=Config(group_content_safety_policies=[{"group_id":"","general_only_enabled":True,"builtin_terms_enabled":True}], group_content_safety_policies_migrated=False); l=TrackingLegacy(); await GroupSafetyService(c).initialize(l); assert l.calls == 0

@pytest.mark.asyncio
async def test_fail_once_retries_migration():
    c=FailOnceConfig(group_content_safety_policies=[], group_content_safety_policies_migrated=False); s=GroupSafetyService(c); await s.initialize(Legacy()); assert c["group_content_safety_policies_migrated"] is False; await s.initialize(Legacy()); assert c["group_content_safety_policies_migrated"] is True

@pytest.mark.asyncio
async def test_legacy_reader_error_keeps_strict():
    class Broken:
        async def list_group_content_safety_records(self): raise RuntimeError("broken")
    c=Config(group_content_safety_policies=[], group_content_safety_policies_migrated=False); s=GroupSafetyService(c); await s.initialize(Broken()); assert await s.list_policies() == [] and c["group_content_safety_policies_migrated"] is False

def test_explicit_strict_is_retained():
    entries,_=normalize_policy_entries([{"group_id":"1","general_only_enabled":True,"builtin_terms_enabled":True}]); assert entries
