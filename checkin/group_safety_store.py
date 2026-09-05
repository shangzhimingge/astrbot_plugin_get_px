from __future__ import annotations

import asyncio
from contextlib import closing

try:
    from ..group_safety import normalize_group_id
except ImportError:
    from group_safety import normalize_group_id


def require_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


class GroupSafetyStoreMixin:
    async def list_group_content_safety_records(self) -> list[dict[str, object]]:
        async with self._lock:
            return await asyncio.to_thread(self._list_group_content_safety_records_sync)

    def _list_group_content_safety_records_sync(self) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT group_id, general_only_enabled, builtin_terms_enabled, updated_by, updated_at FROM group_content_safety ORDER BY group_id").fetchall()
        return [{"group_id": str(row["group_id"]), "general_only_enabled": bool(row["general_only_enabled"]), "builtin_terms_enabled": bool(row["builtin_terms_enabled"]), "updated_by": str(row["updated_by"] or ""), "updated_at": str(row["updated_at"] or "")} for row in rows]

    async def get_group_content_safety(self, group_id: str) -> dict[str, object]:
        normalized = normalize_group_id(group_id)
        async with self._lock:
            return await asyncio.to_thread(
                self._get_group_content_safety_sync, normalized
            )

    async def set_group_content_safety(
        self,
        group_id: str,
        *,
        general_only_enabled: bool,
        builtin_terms_enabled: bool,
        updated_by: str = "",
    ) -> dict[str, object]:
        normalized = normalize_group_id(group_id)
        general_only = require_bool(general_only_enabled, "general_only_enabled")
        builtin_terms = require_bool(builtin_terms_enabled, "builtin_terms_enabled")
        actor = str(updated_by or "").strip()[:128]
        async with self._lock:
            return await asyncio.to_thread(
                self._set_group_content_safety_sync,
                normalized,
                general_only,
                builtin_terms,
                actor,
            )

    def _get_group_content_safety_sync(self, group_id: str) -> dict[str, object]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT group_id, general_only_enabled, builtin_terms_enabled,
                       updated_by, updated_at
                FROM group_content_safety
                WHERE group_id = ?
                """,
                (group_id,),
            ).fetchone()
        if row is None:
            return {
                "group_id": group_id,
                "general_only_enabled": True,
                "builtin_terms_enabled": True,
                "updated_by": "",
                "updated_at": "",
                "is_default": True,
            }
        return {
            "group_id": str(row["group_id"]),
            "general_only_enabled": bool(row["general_only_enabled"]),
            "builtin_terms_enabled": bool(row["builtin_terms_enabled"]),
            "updated_by": str(row["updated_by"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "is_default": False,
        }

    def _set_group_content_safety_sync(
        self,
        group_id: str,
        general_only_enabled: bool,
        builtin_terms_enabled: bool,
        updated_by: str,
    ) -> dict[str, object]:
        updated_at = self.now_iso()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if general_only_enabled and builtin_terms_enabled:
                    conn.execute(
                        "DELETE FROM group_content_safety WHERE group_id = ?",
                        (group_id,),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO group_content_safety (
                            group_id, general_only_enabled, builtin_terms_enabled,
                            updated_by, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(group_id) DO UPDATE SET
                            general_only_enabled = excluded.general_only_enabled,
                            builtin_terms_enabled = excluded.builtin_terms_enabled,
                            updated_by = excluded.updated_by,
                            updated_at = excluded.updated_at
                        """,
                        (
                            group_id,
                            int(general_only_enabled),
                            int(builtin_terms_enabled),
                            updated_by,
                            updated_at,
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._get_group_content_safety_sync(group_id)
