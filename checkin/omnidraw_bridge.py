from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from astrbot.api import logger

LOG_PREFIX = "[GetPx]"
OMNIDRAW_PLUGIN_NAME = "astrbot_plugin_omnidraw"

# 与万象画卷 cmd_checkin 的默认记录结构保持一致，缺用户时按此补齐
_EMPTY_RECORD = {
    "user_id": "",
    "count": 0,
    "last_at": 0,
    "bonus": 0,
    "checkin_at": 0,
}


@dataclass(frozen=True)
class OmnidrawStatus:
    installed: bool = False
    compatible: bool = True
    daily_limit_enabled: bool = False
    checkin_enabled: bool = False
    permission_configured: bool = False
    blocked: bool = False
    unlimited: bool = False
    granted: bool = False
    bonus: int = 0
    remaining: int = 0
    message: str = ""

    @property
    def available(self) -> bool:
        return self.installed and self.compatible and self.daily_limit_enabled


def _config_id_set(value: object) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        source = value
    else:
        source = re.split(r"[\s,]+", str(value or "").replace("\r", "\n"))
    return {str(item).strip() for item in source if str(item).strip()}


class OmnidrawBridge:
    """读取万象画卷额度状态并发放加成。

    ponytail: 直接依赖对方私有成员（_usage_lock/_usage_stats/_persist_usage_stats/
    _daily_image_limit），VPS 部署版 v3.3.23 实测可用；对方升级重命名时
    AttributeError 会被降级为"不可用"，届时再 fork 补公开方法。
    """

    def __init__(self, context, plugin_name: str = OMNIDRAW_PLUGIN_NAME):
        self._context = context
        self._plugin_name = plugin_name

    def _resolve_star(self):
        try:
            meta = self._context.get_registered_star(self._plugin_name)
        except Exception as exc:
            logger.warning(
                f"{LOG_PREFIX} 查询万象画卷插件状态失败: error_type={type(exc).__name__}"
            )
            return None
        if meta is None or not getattr(meta, "activated", False):
            return None
        return getattr(meta, "star_cls", None)

    def _incompatible(self) -> OmnidrawStatus:
        logger.info(f"{LOG_PREFIX} 万象画卷版本过旧，生图额度功能不可用")
        return OmnidrawStatus(installed=True, compatible=False)

    def snapshot(self, user_id: str = "", group_id: str = "") -> OmnidrawStatus:
        star = self._resolve_star()
        if star is None:
            return OmnidrawStatus(installed=False, compatible=False)
        config = getattr(star, "plugin_config", None)
        try:
            limit = int(star._daily_image_limit() or 0)
            with star._usage_lock:
                stats = star._normalize_usage_stats(star._usage_stats)
                record = stats.get("users", {}).get(user_id, {})
                bonus = int(record.get("bonus", 0) or 0)
                used = int(record.get("count", 0) or 0)
                reserved = int(star._quota_reservations.get(user_id, 0) or 0)
        except Exception as exc:
            logger.warning(
                f"{LOG_PREFIX} 万象画卷状态读取失败: error_type={type(exc).__name__}"
            )
            return self._incompatible()
        blocked_ids = _config_id_set(getattr(config, "blocked_users", ""))
        unlimited_ids = _config_id_set(
            getattr(config, "unlimited_users", "")
        ) | _config_id_set(getattr(config, "allowed_users", ""))
        unlimited_groups = _config_id_set(getattr(config, "unlimited_groups", ""))
        usable_ids = _config_id_set(getattr(config, "usable_users", ""))
        return OmnidrawStatus(
            installed=True,
            daily_limit_enabled=limit > 0,
            checkin_enabled=bool(getattr(config, "enable_checkin", False)),
            permission_configured=any(
                (blocked_ids, unlimited_ids, unlimited_groups, usable_ids)
            ),
            blocked=bool(user_id) and user_id in blocked_ids,
            unlimited=bool(user_id)
            and (user_id in unlimited_ids or bool(group_id and group_id in unlimited_groups)),
            bonus=bonus,
            remaining=max(0, limit + bonus - used - reserved) if limit > 0 else 0,
        )

    async def grant(
        self, user_id: str, amount: int, *, display_name: str = ""
    ) -> OmnidrawStatus:
        if amount <= 0:
            return OmnidrawStatus(message="张数无效")
        star = self._resolve_star()
        if star is None:
            return OmnidrawStatus(message="未检测到万象画卷插件")
        try:
            return await asyncio.to_thread(
                self._grant_sync, star, user_id, amount, display_name
            )
        except (AttributeError, TypeError):
            return self._incompatible()
        except Exception as exc:
            logger.warning(
                f"{LOG_PREFIX} 生图额度发放失败: "
                f"user_id={user_id} error_type={type(exc).__name__}"
            )
            return OmnidrawStatus(message="发放失败，请稍后再试")

    def _grant_sync(
        self, star, user_id: str, amount: int, display_name: str
    ) -> OmnidrawStatus:
        limit = int(star._daily_image_limit() or 0)
        if limit <= 0:
            return OmnidrawStatus(
                installed=True, message="万象画卷未启用每日生图限制"
            )
        with star._usage_lock:
            stats = star._normalize_usage_stats(star._usage_stats)
            star._usage_stats = stats
            users = stats.setdefault("users", {})
            record = users.setdefault(user_id, dict(_EMPTY_RECORD))
            record["user_id"] = user_id
            record["bonus"] = int(record.get("bonus", 0) or 0) + amount
            if display_name:
                record["display_name"] = display_name
            stats["total"] = sum(
                int(item.get("count", 0) or 0) for item in users.values()
            )
            star._persist_usage_stats()
            bonus = int(record["bonus"])
            used = int(record.get("count", 0) or 0)
            reserved = int(star._quota_reservations.get(user_id, 0) or 0)
        logger.info(
            f"{LOG_PREFIX} 生图额度发放完成: "
            f"user_id={user_id} amount={amount} bonus={bonus}"
        )
        return OmnidrawStatus(
            installed=True,
            daily_limit_enabled=True,
            granted=True,
            bonus=bonus,
            remaining=max(0, limit + bonus - used - reserved),
            message=f"生图额度 +{amount} 张",
        )
