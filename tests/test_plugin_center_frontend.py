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

def test_policy_state_machine_fields_and_busy_paths():
    source=(PAGE_DIR/'app.js').read_text(encoding='utf-8')
    for token in ['policyLoading','policySaving','policyDeleting','policySnapshot','policyDraft','selectPolicy(']: assert token in source

def test_policy_crud_paths_are_present():
    source=(PAGE_DIR/'app.js').read_text(encoding='utf-8')
    assert source.count('content-safety/group-policy') >= 2
    assert 'content-safety/group-policy/remove' in source

def test_policy_saved_time_and_focus_fallback():
    html=(PAGE_DIR/'index.html').read_text(encoding='utf-8'); source=(PAGE_DIR/'app.js').read_text(encoding='utf-8')
    assert 'id="policySavedAt"' in html and 'requestAnimationFrame' in source and 'policyAddBtn.focus' in source

def test_policy_css_contract():
    css=(PAGE_DIR/'styles.css').read_text(encoding='utf-8')
    assert css.count('{')==css.count('}') and ':focus-visible' in css and ':disabled' in css and 'max-width: 900px' in css and 'max-width: 620px' in css

def _function_body(source, name):
    start = source.index(f"function {name}")
    end = source.find("\nfunction ", start + 10)
    return source[start:] if end < 0 else source[start:end]

def test_policy_named_functions_select_and_reload():
    source=(PAGE_DIR/'app.js').read_text(encoding='utf-8')
    for name in ("selectPolicy", "reloadPolicies", "addGroupPolicy", "saveGroupPolicy", "deleteGroupPolicy"):
        assert f"function {name}" in source
    assert "selectPolicy(" in _function_body(source, "reloadPolicies")
    assert "selectPolicy(" in _function_body(source, "addGroupPolicy")
    assert "selectPolicy(" in _function_body(source, "saveGroupPolicy")

def test_policy_busy_paths_render_after_finally():
    source=(PAGE_DIR/'app.js').read_text(encoding='utf-8')
    for name in ("addGroupPolicy", "saveGroupPolicy", "deleteGroupPolicy"):
        body=_function_body(source,name)
        assert "state.policy" in body and "finally" in body and "renderPolicyManager()" in body

def test_policy_controls_are_disabled_while_busy():
    source=(PAGE_DIR/'app.js').read_text(encoding='utf-8')
    body=_function_body(source,"renderPolicyManager")
    for token in ("policySearch", "policyAddBtn", "policyGeneralToggle", "policyBuiltinToggle", "policySaveBtn", "policyDeleteBtn", "policyAddInput", "policyAddCancel", "aria-busy"):
        assert token in body

def test_policy_snapshot_restore_and_saved_time_reset():
    source=(PAGE_DIR/'app.js').read_text(encoding='utf-8')
    assert "state.policyDraft=snapshot" in source
    assert "state.policySavedAt = 0" in _function_body(source,"selectPolicy")
    assert "state.policySavedAt=Date.now()" in _function_body(source,"saveGroupPolicy")

def test_policy_toggle_draft_and_delete_neighbor():
    source=(PAGE_DIR/'app.js').read_text(encoding='utf-8')
    assert "policyDraft.general_only_enabled" in source and "policyDraft.builtin_terms_enabled" in source
    assert "state.groupPolicies[0]?.group_id" in _function_body(source,"deleteGroupPolicy")

def test_policy_css_exact_interaction_selectors():
    css=(PAGE_DIR/'styles.css').read_text(encoding='utf-8')
    assert ".policy-list-item:focus-visible" in css
    assert ".policy-list-item:disabled" in css
    assert '#policyEditorForm[aria-busy="true"]' in css
