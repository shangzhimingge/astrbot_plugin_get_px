import threading
from types import SimpleNamespace

import pytest

from checkin.omnidraw_bridge import OmnidrawBridge


class FakeOmnidraw:
    def __init__(
        self,
        *,
        enable_daily_limit=True,
        daily_image_limit=20,
        enable_checkin=False,
        blocked_users="",
        unlimited_users="",
        allowed_users="",
        unlimited_groups="",
        usable_users="",
    ):
        self.plugin_config = SimpleNamespace(
            enable_daily_limit=enable_daily_limit,
            daily_image_limit=daily_image_limit,
            enable_checkin=enable_checkin,
            blocked_users=blocked_users,
            unlimited_users=unlimited_users,
            allowed_users=allowed_users,
            unlimited_groups=unlimited_groups,
            usable_users=usable_users,
        )
        self._usage_lock = threading.RLock()
        self._usage_stats = {"date": "2026-09-06", "total": 0, "users": {}}
        self._quota_reservations = {}
        self.persist_calls = 0

    def _daily_image_limit(self):
        if not self.plugin_config.enable_daily_limit:
            return 0
        return max(1, int(self.plugin_config.daily_image_limit))

    def _normalize_usage_stats(self, stats):
        if isinstance(stats, dict) and stats.get("date") == "2026-09-06":
            return stats
        return {"date": "2026-09-06", "total": 0, "users": {}}

    def _persist_usage_stats(self):
        self.persist_calls += 1


class _BrokenOmnidraw:
    """缺少桥所依赖的私有成员，模拟版本过旧。"""

    plugin_config = SimpleNamespace(enable_checkin=False)


def _context_with(star, *, activated=True):
    meta = SimpleNamespace(activated=activated, star_cls=star)
    return SimpleNamespace(
        get_registered_star=lambda name: meta
        if name == "astrbot_plugin_omnidraw"
        else None
    )


def test_snapshot_without_plugin_reports_not_installed():
    bridge = OmnidrawBridge(SimpleNamespace(get_registered_star=lambda name: None))
    status = bridge.snapshot("10001")
    assert not status.installed
    assert not status.compatible
    assert not status.available


def test_snapshot_ignores_inactive_plugin():
    star = FakeOmnidraw()
    bridge = OmnidrawBridge(_context_with(star, activated=False))
    assert not bridge.snapshot("10001").installed


def test_snapshot_reads_switches_and_user_quota():
    star = FakeOmnidraw(enable_checkin=True)
    star._usage_stats["users"]["10001"] = {"count": 6, "bonus": 3, "checkin_at": 1}
    bridge = OmnidrawBridge(_context_with(star))
    status = bridge.snapshot("10001")
    assert status.installed and status.available
    assert status.checkin_enabled
    assert not status.permission_configured
    assert status.bonus == 3
    assert status.remaining == 20 + 3 - 6


def test_snapshot_flags_blocked_and_unlimited_users():
    star = FakeOmnidraw(
        blocked_users="10002",
        unlimited_users="10003",
        allowed_users="10004",
        unlimited_groups="999",
    )
    bridge = OmnidrawBridge(_context_with(star))
    assert bridge.snapshot("10002").blocked
    assert bridge.snapshot("10003").unlimited
    assert bridge.snapshot("10004").unlimited
    assert bridge.snapshot("10005", "999").unlimited
    plain = bridge.snapshot("10006")
    assert not plain.blocked and not plain.unlimited
    assert bridge.snapshot().permission_configured


def test_snapshot_incompatible_version_degrades():
    bridge = OmnidrawBridge(_context_with(_BrokenOmnidraw()))
    status = bridge.snapshot("10001")
    assert status.installed
    assert not status.compatible
    assert not status.available


@pytest.mark.asyncio
async def test_grant_adds_bonus_and_persists():
    star = FakeOmnidraw()
    bridge = OmnidrawBridge(_context_with(star))
    first = await bridge.grant("10001", 5, display_name="测试用户")
    second = await bridge.grant("10001", 5)
    assert first.granted and second.granted
    assert first.message == "生图额度 +5 张"
    assert second.bonus == 10
    record = star._usage_stats["users"]["10001"]
    assert record["bonus"] == 10
    assert record["display_name"] == "测试用户"
    assert record["checkin_at"] == 0
    assert star.persist_calls == 2


@pytest.mark.asyncio
async def test_grant_rejects_when_daily_limit_disabled():
    star = FakeOmnidraw(enable_daily_limit=False)
    bridge = OmnidrawBridge(_context_with(star))
    status = await bridge.grant("10001", 5)
    assert not status.granted
    assert "未启用每日生图限制" in status.message
    assert star.persist_calls == 0


@pytest.mark.asyncio
async def test_grant_rejects_nonpositive_amount():
    bridge = OmnidrawBridge(_context_with(FakeOmnidraw()))
    status = await bridge.grant("10001", 0)
    assert not status.granted


@pytest.mark.asyncio
async def test_grant_without_plugin_fails():
    bridge = OmnidrawBridge(SimpleNamespace(get_registered_star=lambda name: None))
    status = await bridge.grant("10001", 5)
    assert not status.granted


@pytest.mark.asyncio
async def test_grant_swallows_unexpected_error():
    star = FakeOmnidraw()

    def _boom():
        raise RuntimeError("disk error")

    star._persist_usage_stats = _boom
    bridge = OmnidrawBridge(_context_with(star))
    status = await bridge.grant("10001", 5)
    assert not status.granted
    assert status.message == "发放失败，请稍后再试"
