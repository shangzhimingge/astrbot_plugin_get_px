from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

try:
    from astrbot.api.all import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

CONFIG_KEY = "group_content_safety_policies"
PRIVATE_CONFIG_KEY = "private_content_safety_policies"
MIGRATION_KEY = "group_content_safety_policies_migrated"
TEMPLATE_KEY = "group_policy"
PRIVATE_TEMPLATE_KEY = "private_policy"
MAX_GROUP_ID_LENGTH = 128


def _normalize(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{key} is required")
    if len(value) > MAX_GROUP_ID_LENGTH:
        raise ValueError(f"{key} must not exceed {MAX_GROUP_ID_LENGTH} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{key} contains invalid control characters")
    return value


def normalize_group_id(value: object) -> str:
    return _normalize(value, "group_id")


def normalize_user_id(value: object) -> str:
    return _normalize(value, "user_id")


def strict_policy(identifier: str, *, private: bool = False) -> dict[str, object]:
    return {
        "user_id" if private else "group_id": identifier,
        "general_only_enabled": True,
        "builtin_terms_enabled": True,
        "updated_by": "",
        "updated_at": "",
        "is_default": True,
    }


def _normalize_entries(raw: object, *, private: bool = False):
    key = "user_id" if private else "group_id"
    template = PRIVATE_TEMPLATE_KEY if private else TEMPLATE_KEY
    normalize_id = normalize_user_id if private else normalize_group_id
    if not isinstance(raw, list):
        return [], [f"{key} policy list must be a list"]
    entries, warnings, seen = [], [], set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            warnings.append(f"entry {index}: must be an object")
            continue
        try:
            identifier = normalize_id(item.get(key))
            if type(item.get("general_only_enabled")) is not bool:
                raise ValueError("general_only_enabled must be a boolean")
            if type(item.get("builtin_terms_enabled")) is not bool:
                raise ValueError("builtin_terms_enabled must be a boolean")
        except ValueError as exc:
            warnings.append(f"entry {index}: {exc}")
            continue
        if identifier in seen:
            warnings.append(f"entry {index}: duplicate {key} {identifier}")
            continue
        seen.add(identifier)
        entries.append(
            {
                "__template_key": template,
                key: identifier,
                "general_only_enabled": item["general_only_enabled"],
                "builtin_terms_enabled": item["builtin_terms_enabled"],
                "updated_by": str(item.get("updated_by") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
        )
    return sorted(entries, key=lambda entry: entry[key]), warnings


def normalize_policy_entries(raw: object):
    return _normalize_entries(raw)


class SessionSafetyService:
    def __init__(self, config: Any, *, log_prefix: str = "[GetPx]"):
        self.config = config
        self.log_prefix = log_prefix
        self._lock = asyncio.Lock()
        self._policies: dict[str, dict[str, object]] = {}
        self._private_policies: dict[str, dict[str, object]] = {}

    @staticmethod
    def _scope(private: bool):
        return (
            (PRIVATE_CONFIG_KEY, "user_id", PRIVATE_TEMPLATE_KEY)
            if private
            else (CONFIG_KEY, "group_id", TEMPLATE_KEY)
        )

    def _source(self, private: bool):
        return self._private_policies if private else self._policies

    def _records(self, entries, *, private: bool):
        _, key, _ = self._scope(private)
        return {
            str(entry[key]): {
                key: str(entry[key]),
                "general_only_enabled": entry["general_only_enabled"],
                "builtin_terms_enabled": entry["builtin_terms_enabled"],
                "updated_by": str(entry.get("updated_by") or ""),
                "updated_at": str(entry.get("updated_at") or ""),
                "is_default": False,
            }
            for entry in entries
        }

    def _install(self, entries, *, private: bool = False):
        target = self._source(private)
        target.clear()
        target.update(self._records(entries, private=private))

    def _entries(self, records, *, private: bool):
        _, key, template = self._scope(private)
        return [
            {
                "__template_key": template,
                key: identifier,
                "general_only_enabled": record["general_only_enabled"],
                "builtin_terms_enabled": record["builtin_terms_enabled"],
                "updated_by": str(record.get("updated_by") or ""),
                "updated_at": str(record.get("updated_at") or ""),
            }
            for identifier, record in sorted(records.items())
        ]

    def _save_scope(self, *, private: bool, candidate, migrated=None):
        config_key, _, _ = self._scope(private)
        old_present = config_key in self.config
        old_value = self.config.get(config_key)
        old_copy = deepcopy(old_value)
        old_migration_present = MIGRATION_KEY in self.config
        old_migration = self.config.get(MIGRATION_KEY)
        serialized = self._entries(candidate, private=private)
        if isinstance(old_value, list):
            old_value[:] = deepcopy(serialized)
        else:
            self.config[config_key] = deepcopy(serialized)
        if not private and migrated is not None:
            self.config[MIGRATION_KEY] = bool(migrated)
        try:
            saver = getattr(self.config, "save_config", None)
            if not callable(saver):
                raise RuntimeError("config.save_config is required")
            saver()
        except Exception:
            if isinstance(old_value, list):
                old_value[:] = old_copy
                self.config[config_key] = old_value
            elif old_present:
                self.config[config_key] = old_copy
            else:
                self.config.pop(config_key, None)
            if not private:
                if old_migration_present:
                    self.config[MIGRATION_KEY] = old_migration
                else:
                    self.config.pop(MIGRATION_KEY, None)
            raise

    def _log_warnings(self, source: str, warnings):
        for warning in warnings:
            logger.warning(f"{self.log_prefix} {source}: {warning}")

    async def initialize(self, legacy_store):
        async with self._lock:
            raw_private = self.config.get(PRIVATE_CONFIG_KEY, [])
            private_entries, warnings = _normalize_entries(raw_private, private=True)
            self._log_warnings("private config", warnings)
            self._install(private_entries, private=True)
            if raw_private != private_entries:
                try:
                    self._save_scope(
                        private=True, candidate=deepcopy(self._private_policies)
                    )
                except Exception as exc:
                    self._log_warnings(
                        "private config",
                        [f"save failed error_type={type(exc).__name__}"],
                    )

            raw_group = self.config.get(CONFIG_KEY, [])
            group_entries, warnings = _normalize_entries(raw_group)
            self._log_warnings("config", warnings)
            migrated = bool(self.config.get(MIGRATION_KEY, False))
            use_legacy = not migrated and isinstance(raw_group, list) and not raw_group
            if use_legacy:
                try:
                    group_entries, warnings = _normalize_entries(
                        await legacy_store.list_group_content_safety_records()
                    )
                    self._log_warnings("legacy", warnings)
                except Exception as exc:
                    self._install([], private=False)
                    self._log_warnings(
                        "legacy", [f"read failed error_type={type(exc).__name__}"]
                    )
                    return
            self._install(group_entries, private=False)
            if isinstance(raw_group, list) and migrated and raw_group == group_entries:
                return
            try:
                self._save_scope(
                    private=False,
                    candidate=deepcopy(self._policies),
                    migrated=True,
                )
            except Exception as exc:
                self._install([], private=False)
                self._log_warnings(
                    "legacy" if use_legacy else "config",
                    [f"save failed error_type={type(exc).__name__}"],
                )

    async def _list(self, *, private: bool = False):
        async with self._lock:
            return [dict(record) for _, record in sorted(self._source(private).items())]

    async def _get(self, identifier, *, private: bool = False):
        _, key, _ = self._scope(private)
        identifier = _normalize(identifier, key)
        async with self._lock:
            return dict(
                self._source(private).get(
                    identifier, strict_policy(identifier, private=private)
                )
            )

    async def _upsert(
        self,
        identifier,
        *,
        general_only_enabled,
        builtin_terms_enabled,
        updated_by="",
        private=False,
    ):
        _, key, _ = self._scope(private)
        identifier = _normalize(identifier, key)
        if (
            type(general_only_enabled) is not bool
            or type(builtin_terms_enabled) is not bool
        ):
            raise ValueError("policy values must be booleans")
        async with self._lock:
            candidate = deepcopy(self._source(private))
            candidate[identifier] = {
                key: identifier,
                "general_only_enabled": general_only_enabled,
                "builtin_terms_enabled": builtin_terms_enabled,
                "updated_by": str(updated_by or ""),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "is_default": False,
            }
            self._save_scope(private=private, candidate=candidate, migrated=True)
            target = self._source(private)
            target.clear()
            target.update(candidate)
            return dict(target[identifier])

    async def _remove(self, identifier, *, private=False):
        _, key, _ = self._scope(private)
        identifier = _normalize(identifier, key)
        async with self._lock:
            source = self._source(private)
            if identifier not in source:
                return False, strict_policy(identifier, private=private)
            candidate = deepcopy(source)
            del candidate[identifier]
            self._save_scope(private=private, candidate=candidate, migrated=True)
            source.clear()
            source.update(candidate)
            return True, strict_policy(identifier, private=private)

    async def list_group_policies(self):
        return await self._list()

    async def get_group_policy(self, group_id):
        return await self._get(group_id)

    async def upsert_group_policy(self, group_id, **kwargs):
        return await self._upsert(group_id, **kwargs)

    async def remove_group_policy(self, group_id):
        return await self._remove(group_id)

    async def list_private_policies(self):
        return await self._list(private=True)

    async def get_private_policy(self, user_id):
        return await self._get(user_id, private=True)

    async def upsert_private_policy(self, user_id, **kwargs):
        return await self._upsert(user_id, private=True, **kwargs)

    async def remove_private_policy(self, user_id):
        return await self._remove(user_id, private=True)

    async def list_policies(self):
        return await self.list_group_policies()

    async def get_policy(self, group_id):
        return await self.get_group_policy(group_id)

    async def upsert_policy(self, group_id, **kwargs):
        return await self.upsert_group_policy(group_id, **kwargs)

    async def remove_policy(self, group_id):
        return await self.remove_group_policy(group_id)


GroupSafetyService = SessionSafetyService
