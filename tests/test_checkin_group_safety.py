from __future__ import annotations

import asyncio
from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path

import pytest

from checkin import CheckinStore
from checkin.schema import CHECKIN_DB_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_group_policy_defaults_are_strict_without_writing_a_row() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = CheckinStore(tmp)
        policy = await store.get_group_content_safety("group-a")
        assert policy == {
            "group_id": "group-a",
            "general_only_enabled": True,
            "builtin_terms_enabled": True,
            "updated_by": "",
            "updated_at": "",
            "is_default": True,
        }
        with closing(sqlite3.connect(store._db_path)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM group_content_safety").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_group_policy_switches_are_independent_and_persist() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = CheckinStore(tmp)
        first = await store.set_group_content_safety(
            "group-a",
            general_only_enabled=False,
            builtin_terms_enabled=True,
            updated_by="test",
        )
        assert first["general_only_enabled"] is False
        assert first["builtin_terms_enabled"] is True
        reopened = CheckinStore(tmp)
        assert await reopened.get_group_content_safety("group-a") == first

        reset = await reopened.set_group_content_safety(
            "group-a",
            general_only_enabled=True,
            builtin_terms_enabled=True,
            updated_by="test",
        )
        assert reset["is_default"] is True


@pytest.mark.asyncio
async def test_checkin_snapshot_import_does_not_reset_group_runtime_policy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = CheckinStore(tmp)
        snapshot = await store.export_snapshot()
        await store.set_group_content_safety(
            "group-a",
            general_only_enabled=False,
            builtin_terms_enabled=False,
        )
        await store.import_snapshot(snapshot)
        policy = await store.get_group_content_safety("group-a")
        assert policy["general_only_enabled"] is False
        assert policy["builtin_terms_enabled"] is False


@pytest.mark.asyncio
async def test_group_policy_validates_ids_bools_and_serializes_concurrent_writes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = CheckinStore(tmp)
        with pytest.raises(ValueError):
            await store.get_group_content_safety(" ")
        with pytest.raises(ValueError):
            await store.get_group_content_safety("x" * 129)
        with pytest.raises(ValueError):
            await store.set_group_content_safety(
                "group-a",
                general_only_enabled="false",
                builtin_terms_enabled=True,
            )

        await asyncio.gather(*(
            store.set_group_content_safety(
                "group-a",
                general_only_enabled=bool(index % 2),
                builtin_terms_enabled=bool((index // 2) % 2),
                updated_by=str(index),
            )
            for index in range(16)
        ))
        policy = await store.get_group_content_safety("group-a")
        assert type(policy["general_only_enabled"]) is bool
        assert type(policy["builtin_terms_enabled"]) is bool


def test_v2_database_migrates_to_v3_with_consistent_backup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        original = CheckinStore(tmp)
        with closing(sqlite3.connect(original._db_path)) as conn:
            conn.execute("INSERT INTO checkin_global_events (event_type, date_value, name, created_by, created_at, updated_at) VALUES ('solar', '09-04', 'kept', '', 'now', 'now')")
            conn.execute("PRAGMA user_version = 2")
            conn.commit()

        migrated = CheckinStore(tmp)
        with closing(sqlite3.connect(migrated._db_path)) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == CHECKIN_DB_SCHEMA_VERSION
            assert conn.execute("SELECT name FROM checkin_global_events").fetchone()[0] == "kept"
            assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='group_content_safety'").fetchone()

        backups = list((Path(tmp) / "checkin_migration_backups").glob("checkin-v2-*.sqlite3"))
        assert len(backups) == 1
        with closing(sqlite3.connect(backups[0])) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
            assert conn.execute("SELECT name FROM checkin_global_events").fetchone()[0] == "kept"


@pytest.mark.parametrize("old_version", [1, 2])
def test_known_old_versions_migrate_once_and_v3_reopen_is_idempotent(old_version) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = CheckinStore(tmp)
        with closing(sqlite3.connect(store._db_path)) as conn:
            conn.execute(f"PRAGMA user_version = {old_version}")
            conn.commit()
        CheckinStore(tmp)
        backup_dir = Path(tmp) / "checkin_migration_backups"
        before = list(backup_dir.glob("*.sqlite3"))
        assert len(before) == 1
        CheckinStore(tmp)
        assert list(backup_dir.glob("*.sqlite3")) == before


def test_unknown_future_schema_is_rejected_without_migration_backup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = CheckinStore(tmp)
        with closing(sqlite3.connect(store._db_path)) as conn:
            conn.execute("PRAGMA user_version = 999")
            conn.commit()
        with pytest.raises(RuntimeError, match="unsupported"):
            CheckinStore(tmp)
        assert not (Path(tmp) / "checkin_migration_backups").exists()
