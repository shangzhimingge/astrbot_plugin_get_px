from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

CONFIG_KEY = "group_content_safety_policies"
MIGRATION_KEY = "group_content_safety_policies_migrated"
TEMPLATE_KEY = "group_policy"
MAX_GROUP_ID_LENGTH = 128

def normalize_group_id(value: object) -> str:
    if not isinstance(value, str): raise ValueError("group_id must be a string")
    value = value.strip()
    if not value: raise ValueError("group_id is required")
    if len(value) > MAX_GROUP_ID_LENGTH: raise ValueError(f"group_id must not exceed {MAX_GROUP_ID_LENGTH} characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("group_id contains invalid control characters")
    return value

def strict_policy(group_id: str) -> dict[str, object]:
    return {"group_id": group_id, "general_only_enabled": True, "builtin_terms_enabled": True, "updated_by": "", "updated_at": "", "is_default": True}

def normalize_policy_entries(raw: object) -> tuple[list[dict[str, object]], list[str]]:
    if not isinstance(raw, list): return [], ["group policy list must be a list"]
    result, warnings, seen = [], [], set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict): warnings.append(f"entry {index}: must be an object"); continue
        try:
            gid = normalize_group_id(item.get("group_id"))
            if type(item.get("general_only_enabled")) is not bool: raise ValueError("general_only_enabled must be a boolean")
            if type(item.get("builtin_terms_enabled")) is not bool: raise ValueError("builtin_terms_enabled must be a boolean")
        except ValueError as exc: warnings.append(f"entry {index}: {exc}"); continue
        if gid in seen: warnings.append(f"entry {index}: duplicate group_id {gid}"); continue
        seen.add(gid)
        result.append({"__template_key": TEMPLATE_KEY, "group_id": gid, "general_only_enabled": item["general_only_enabled"], "builtin_terms_enabled": item["builtin_terms_enabled"]})
    result.sort(key=lambda x: str(x["group_id"]))
    return result, warnings

class GroupSafetyService:
    def __init__(self, config: Any, *, log_prefix: str = "[GetPx]") -> None:
        self.config, self.log_prefix, self._lock, self._policies = config, log_prefix, asyncio.Lock(), {}
    def _install(self, entries):
        self._policies = {str(x["group_id"]): {"group_id": str(x["group_id"]), "general_only_enabled": x["general_only_enabled"], "builtin_terms_enabled": x["builtin_terms_enabled"], "updated_by": "", "updated_at": "", "is_default": False} for x in entries}
    def _save_candidate(self, entries, migrated=True):
        old, old_migrated = self.config.get(CONFIG_KEY, []), self.config.get(MIGRATION_KEY, False)
        self.config[CONFIG_KEY], self.config[MIGRATION_KEY] = [dict(x) for x in entries], migrated
        try:
            saver = getattr(self.config, "save_config", None)
            if not callable(saver): raise RuntimeError("config.save_config is required")
            saver()
        except Exception:
            self.config[CONFIG_KEY], self.config[MIGRATION_KEY] = old, old_migrated
            raise
        self._install(entries)
    async def initialize(self, legacy_store):
        async with self._lock:
            entries, warnings = normalize_policy_entries(self.config.get(CONFIG_KEY, []))
            if self.config.get(MIGRATION_KEY, False): self._install(entries); return
            if entries:
                self._save_candidate(entries, True)
                return
            legacy = await legacy_store.list_group_content_safety_records()
            self._save_candidate(normalize_policy_entries(legacy)[0], True)
    async def list_policies(self):
        async with self._lock: return [dict(self._policies[k]) for k in sorted(self._policies)]
    async def get_policy(self, group_id):
        gid = normalize_group_id(group_id)
        async with self._lock: return dict(self._policies.get(gid, strict_policy(gid)))
    async def upsert_policy(self, group_id, *, general_only_enabled, builtin_terms_enabled, updated_by=""):
        gid = normalize_group_id(group_id)
        if type(general_only_enabled) is not bool: raise ValueError("general_only_enabled must be a boolean")
        if type(builtin_terms_enabled) is not bool: raise ValueError("builtin_terms_enabled must be a boolean")
        async with self._lock:
            entries = [{"__template_key": TEMPLATE_KEY, "group_id": k, "general_only_enabled": v["general_only_enabled"], "builtin_terms_enabled": v["builtin_terms_enabled"]} for k,v in self._policies.items() if k != gid]
            entries.append({"__template_key": TEMPLATE_KEY, "group_id": gid, "general_only_enabled": general_only_enabled, "builtin_terms_enabled": builtin_terms_enabled}); entries.sort(key=lambda x: str(x["group_id"]))
            self._save_candidate(entries); value = dict(self._policies[gid]); value["updated_by"], value["updated_at"] = str(updated_by or ""), datetime.now(timezone.utc).isoformat(); return value
    async def remove_policy(self, group_id):
        gid = normalize_group_id(group_id)
        async with self._lock:
            removed = gid in self._policies
            if removed: self._save_candidate([{ "__template_key": TEMPLATE_KEY, "group_id": k, "general_only_enabled": v["general_only_enabled"], "builtin_terms_enabled": v["builtin_terms_enabled"]} for k,v in self._policies.items() if k != gid])
            return removed, strict_policy(gid)
