"""Test issue_pipeline với Notion/LLM/GitHub giả."""
import asyncio

import pytest

import config
import issue_pipeline as ip
from issue_models import BugInput, Draft, IssueFields
from notion_fixtures import bug_page, url_prop

ISSUE_URL = "https://github.com/t/g/issues/34"


# ---------------------------------------------------------------- bug_from_page

def test_bug_from_page_reads_all_fields():
    bug = ip.bug_from_page(bug_page(), "mô tả", "b1", [("img", "https://s3/x")])
    assert bug.page_id == "page-1"
    assert bug.bug_id == "BUG-12"
    assert bug.notion_url == "https://www.notion.so/page1"
    assert bug.title == "Rớt mạng"
    assert (bug.description, bug.steps) == ("mô tả", "b1")
    assert (bug.severity, bug.version, bug.modules) == ("Cao", "v1.2", "Server")
    assert (bug.character, bug.level, bug.map_name) == ("Thiếu Lâm", 90, "Tương Dương")
    assert bug.images == [("img", "https://s3/x")]
    assert bug.github_issue == ""


def test_bug_from_old_page_missing_new_columns():
    page = bug_page(character=None, level=None, map=None, github_issue=None)
    bug = ip.bug_from_page(page, "", "", [])
    assert (bug.character, bug.level, bug.map_name, bug.github_issue) == ("", None, "", "")


def test_bug_from_page_existing_issue():
    bug = ip.bug_from_page(bug_page(github_issue=url_prop(ISSUE_URL)), "", "", [])
    assert bug.github_issue == ISSUE_URL


def test_ext_from_content_type_then_url():
    assert ip._ext("https://s3/x", "image/png") == ".png"
    assert ip._ext("https://s3/x", "image/jpeg; charset=binary") == ".jpg"
    assert ip._ext("https://s3/a/b.webp?sig=1", "application/octet-stream") == ".webp"
    assert ip._ext("https://s3/a/b", "") == ".jpg"


# ---------------------------------------------------------------- draft

def _fields(**kw):
    base = dict(title="T", symptom="S", steps=["a"], log="", domain="")
    base.update(kw)
    return IssueFields(**base)


def _bug(**kw):
    base = dict(page_id="page-1", bug_id="BUG-12", notion_url="https://www.notion.so/page1", title="T")
    base.update(kw)
    return BugInput(**base)


def _fake_llm(monkeypatch, result):
    async def fake(bug, qa, final):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(ip.llm_client, "draft_issue", fake)


def test_draft_final_forces_ready(monkeypatch):
    _fake_llm(monkeypatch, Draft("need_info", ["q?"], _fields()))
    d = asyncio.run(ip.draft(_bug(), [], final=True))
    assert d.status == "ready" and d.questions == []


def test_draft_not_final_keeps_need_info(monkeypatch):
    _fake_llm(monkeypatch, Draft("need_info", ["q?"], _fields()))
    d = asyncio.run(ip.draft(_bug(), [], final=False))
    assert d.status == "need_info" and d.questions == ["q?"]


def test_draft_wraps_llm_error(monkeypatch):
    _fake_llm(monkeypatch, ip.llm_client.LLMError("LLM trả lỗi HTTP 500"))
    with pytest.raises(ip.PipelineError, match="500"):
        asyncio.run(ip.draft(_bug(), [], final=False))


# ---------------------------------------------------------------- publish

def _patch_publish(monkeypatch, page, *, download_fails=False, github_fails=False, notion_write_fails=False):
    calls = []

    async def get_page(pid):
        return page

    async def create_issue(title, body, labels):
        if github_fails:
            raise ip.gh.GitHubError("GitHub trả lỗi HTTP 403 khi tạo issue")
        calls.append(("issue", title, body, labels))
        return 34, ISSUE_URL

    async def put_asset(path, data, message):
        calls.append(("asset", path, data))
        return f"https://gh/{path}"

    async def set_github_issue(pid, url):
        if notion_write_fails:
            raise RuntimeError("notion down")
        calls.append(("set", pid, url))

    async def log_history(pid, text):
        calls.append(("hist", pid, text))

    async def download(url):
        if download_fails:
            raise RuntimeError("404")
        return b"img", "image/png"

    monkeypatch.setattr(ip.nc, "get_page", get_page)
    monkeypatch.setattr(ip.nc, "set_github_issue", set_github_issue)
    monkeypatch.setattr(ip.nc, "log_history", log_history)
    monkeypatch.setattr(ip.gh, "create_issue", create_issue)
    monkeypatch.setattr(ip.gh, "put_asset", put_asset)
    monkeypatch.setattr(ip, "_download", download)
    monkeypatch.setattr(config, "GITHUB_LABELS", ["bug"])
    return calls


def test_publish_refuses_when_github_column_missing(monkeypatch):
    """Thiếu cột GitHub Issue → không ghi ngược được → mỗi lần chạy lại sẽ tạo issue trùng. Phải dừng trước."""
    calls = _patch_publish(monkeypatch, bug_page(github_issue=None))
    with pytest.raises(ip.PipelineError, match="GitHub Issue"):
        asyncio.run(ip.publish(_bug(), _fields()))
    assert not [c for c in calls if c[0] == "issue"]


def test_publish_existing_issue_short_circuits(monkeypatch):
    calls = _patch_publish(monkeypatch, bug_page(github_issue=url_prop(ISSUE_URL)))
    assert asyncio.run(ip.publish(_bug(), _fields())) == ISSUE_URL
    assert calls == []


def test_publish_happy_path(monkeypatch):
    calls = _patch_publish(monkeypatch, bug_page())
    bug = _bug(images=[("aaaa-bbbb", "https://s3/x")])
    assert asyncio.run(ip.publish(bug, _fields(title="Rớt mạng khi vào map"))) == ISSUE_URL

    assert calls[0] == ("asset", "bug-assets/BUG-12/aaaabbbb.png", b"img")
    kind, title, body, labels = calls[1]
    assert kind == "issue"
    assert title == "[BUG-12] Rớt mạng khi vào map"
    assert "![BUG-12 ảnh 1](https://gh/bug-assets/BUG-12/aaaabbbb.png)" in body
    assert labels == ["bug"]
    assert ("set", "page-1", ISSUE_URL) in calls
    assert ("hist", "page-1", "Tạo GitHub issue #34") in calls


def test_publish_image_failure_is_counted(monkeypatch):
    calls = _patch_publish(monkeypatch, bug_page(), download_fails=True)
    bug = _bug(images=[("dead", "https://api.telegram.org/file/botX/photos/1.jpg")])
    asyncio.run(ip.publish(bug, _fields()))
    body = [c for c in calls if c[0] == "issue"][0][2]
    assert "_(1 ảnh không tải được — xem trên Notion)_" in body
    assert not [c for c in calls if c[0] == "asset"]


def test_publish_github_error_raises_pipeline_error(monkeypatch):
    _patch_publish(monkeypatch, bug_page(), github_fails=True)
    with pytest.raises(ip.PipelineError, match="403"):
        asyncio.run(ip.publish(_bug(), _fields()))


def test_publish_notion_writeback_failure_still_returns_url(monkeypatch):
    _patch_publish(monkeypatch, bug_page(), notion_write_fails=True)
    assert asyncio.run(ip.publish(_bug(), _fields())) == ISSUE_URL


def test_load_bug_wraps_notion_error(monkeypatch):
    async def boom(pid):
        raise RuntimeError("404")
    monkeypatch.setattr(ip.nc, "get_page", boom)
    with pytest.raises(ip.PipelineError):
        asyncio.run(ip.load_bug("page-1"))


def test_enabled_follows_config(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_ENABLED", False)
    assert ip.enabled() is False
    monkeypatch.setattr(config, "GITHUB_ENABLED", True)
    assert ip.enabled() is True
