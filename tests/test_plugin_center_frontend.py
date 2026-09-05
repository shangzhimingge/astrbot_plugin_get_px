from __future__ import annotations

import re
from pathlib import Path


PAGE_DIR = Path(__file__).resolve().parents[1] / "pages" / "pluginCenter"


def test_plugin_center_page_exposes_management_workspaces() -> None:
    html = (PAGE_DIR / "index.html").read_text(encoding="utf-8")
    assert "插件管理中心" in html
    assert 'data-view="ranking"' in html
    assert 'data-view="members"' in html
    assert 'data-view="safety"' in html
    assert 'data-view="policies"' in html
    assert 'id="policiesView"' in html
    assert 'id="policyAddDialog"' in html
    assert 'id="policyList"' in html
    assert 'id="policySearch"' in html
    assert 'data-view="data"' in html
    assert "群签到轨道" in html
    assert "签到成员数值" in html
    assert "内置安全词" in html
    assert "签到数据管理" in html
    assert "imageHistory" not in html
    assert "cacheStats" not in html
    assert "schema v6" in html


def test_plugin_center_import_accepts_json_backups_only() -> None:
    html = (PAGE_DIR / "index.html").read_text(encoding="utf-8")
    script = (PAGE_DIR / "app.js").read_text(encoding="utf-8")
    assert 'accept="application/json,.json"' in html
    assert "只能选择 JSON 备份文件。" in script
    assert "备份文件不能超过 5 MiB。" in script
    assert "恢复签到数据" in script
    assert "sqlite" not in html.lower()
    assert "sqlite" not in script.lower()


def test_plugin_center_uses_relative_bridge_endpoints() -> None:
    source = (PAGE_DIR / "app.js").read_text(encoding="utf-8")
    assert "window.AstrBotPluginPage" in source
    assert "bridge.ready()" in source
    assert 'bridge.download("checkin-export"' in source
    assert 'bridge.upload("checkin-import"' in source
    endpoints = re.findall(r'(?:apiGet|apiPost)\("([^"]+)"', source)
    assert endpoints
    assert all(not endpoint.startswith("/") for endpoint in endpoints)
    assert "image-history" not in source
    assert "cache_cleanup" not in source


def test_plugin_center_exposes_independent_group_safety_switches() -> None:
    html = (PAGE_DIR / "index.html").read_text(encoding="utf-8")
    source = (PAGE_DIR / "app.js").read_text(encoding="utf-8")
    assert 'safetyGroupInput' not in html
    assert 'content-safety/group-policies' in source
    assert 'content-safety/group-policy/remove' in source
    assert "删除后恢复默认严格策略" in html
    assert 'apiPost("content-safety/group-policy"' in source
    assert "policySaving" in source or "policyDeleteBtn" in source
    assert "安全策略已锁定" not in html
