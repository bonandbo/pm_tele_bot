"""Test llm_client: dựng prompt, parse JSON, retry (không gọi mạng thật)."""
import asyncio
import json

import httpx
import pytest

import config
import llm_client
from issue_models import BugInput


def _bug(**kw) -> BugInput:
    base = dict(page_id="p1", bug_id="BUG-3", notion_url="u", title="Game lỗi",
                description="Vào game bị văng", severity="Cao")
    base.update(kw)
    return BugInput(**base)


def _reply(status="ready", questions=None, **issue) -> str:
    fields = {"title": "T", "symptom": "S", "steps": [], "log": "", "domain": ""}
    fields.update(issue)
    return json.dumps({"status": status, "questions": questions or [], "issue": fields})


def _setup(monkeypatch, handler):
    monkeypatch.setattr(llm_client, "_TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://llm.test/v1/")
    monkeypatch.setattr(config, "LLM_API_KEY", "k-test")
    monkeypatch.setattr(config, "LLM_MODEL", "test-model")


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


# ---------------------------------------------------------------- parse_draft

def test_parse_ready():
    d = llm_client.parse_draft(_reply(steps=["a", "b"], domain="client"), "fb")
    assert d.status == "ready"
    assert d.questions == []
    assert d.issue.steps == ["a", "b"]
    assert d.issue.domain == "client"
    assert d.issue.title == "T"


def test_parse_strips_json_fence():
    d = llm_client.parse_draft("```json\n" + _reply() + "\n```", "fb")
    assert d.status == "ready"


def test_parse_invalid_status_raises():
    with pytest.raises(llm_client.LLMError):
        llm_client.parse_draft(_reply(status="maybe"), "fb")


def test_parse_broken_json_raises():
    with pytest.raises(llm_client.LLMError):
        llm_client.parse_draft("xin chào, đây không phải JSON", "fb")


def test_parse_non_object_raises():
    with pytest.raises(llm_client.LLMError):
        llm_client.parse_draft("[1, 2]", "fb")


def test_parse_unknown_domain_becomes_empty():
    assert llm_client.parse_draft(_reply(domain="gameplay"), "fb").issue.domain == ""


def test_parse_domain_is_normalised():
    assert llm_client.parse_draft(_reply(domain=" Server "), "fb").issue.domain == "server"


def test_need_info_without_questions_becomes_ready():
    assert llm_client.parse_draft(_reply(status="need_info"), "fb").status == "ready"


def test_ready_drops_questions():
    d = llm_client.parse_draft(_reply(status="ready", questions=["q?"]), "fb")
    assert d.questions == []


def test_questions_capped_at_three():
    d = llm_client.parse_draft(_reply(status="need_info", questions=["1", "2", "3", "4"]), "fb")
    assert d.questions == ["1", "2", "3"]


def test_questions_as_string_is_single_question():
    text = json.dumps({"status": "need_info", "questions": "Bạn dùng skill gì?",
                       "issue": {"title": "T", "symptom": "S"}})
    d = llm_client.parse_draft(text, "fb")
    assert d.status == "need_info"
    assert d.questions == ["Bạn dùng skill gì?"]


def test_steps_string_split_and_numbering_removed():
    d = llm_client.parse_draft(_reply(steps="1. Vào map\n2) Đánh quái\n- Rớt\n\n"), "fb")
    assert d.issue.steps == ["Vào map", "Đánh quái", "Rớt"]


def test_steps_list_numbering_removed():
    d = llm_client.parse_draft(_reply(steps=["1. Vào map", "2. Đánh quái"]), "fb")
    assert d.issue.steps == ["Vào map", "Đánh quái"]


def test_step_starting_with_decimal_is_kept():
    d = llm_client.parse_draft(_reply(steps=["2.5 giây sau thì crash"]), "fb")
    assert d.issue.steps == ["2.5 giây sau thì crash"]


def test_empty_title_uses_fallback():
    assert llm_client.parse_draft(_reply(title=""), "Tiêu đề Notion").issue.title == "Tiêu đề Notion"


def test_missing_issue_object_gives_empty_fields():
    d = llm_client.parse_draft(json.dumps({"status": "ready"}), "fb")
    assert d.issue.title == "fb"
    assert d.issue.symptom == ""
    assert d.issue.steps == []


# ---------------------------------------------------------------- build_messages

def test_build_messages_includes_bug_and_qa():
    msgs = llm_client.build_messages(_bug(), [("Q1?", "A1")], final=False)
    assert msgs[0]["role"] == "system"
    assert "JSON" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert msgs[1]["role"] == "user"
    assert "Game lỗi" in user and "Vào game bị văng" in user
    assert "Severity: Cao" in user
    assert "Q1?" in user and "A1" in user
    assert llm_client.FINAL_NOTE not in user


def test_build_messages_final_note():
    user = llm_client.build_messages(_bug(), [], final=True)[1]["content"]
    assert llm_client.FINAL_NOTE in user


def test_build_messages_omits_environment():
    bug = _bug(character="Thiếu Lâm", level=90, map_name="Tương Dương")
    user = llm_client.build_messages(bug, [], final=False)[1]["content"]
    assert "Thiếu Lâm" not in user and "Tương Dương" not in user


# ---------------------------------------------------------------- draft_issue (mạng giả)

def test_draft_issue_sends_openai_request(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok(_reply())

    _setup(monkeypatch, handler)
    d = asyncio.run(llm_client.draft_issue(_bug(), [], final=False))
    assert d.status == "ready"
    req = seen[0]
    assert str(req.url) == "https://llm.test/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer k-test"
    body = json.loads(req.content)
    assert body["model"] == "test-model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.2


def _sent_body(monkeypatch, disable_thinking):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return _ok(_reply())

    _setup(monkeypatch, handler)
    monkeypatch.setattr(config, "LLM_DISABLE_THINKING", disable_thinking)
    asyncio.run(llm_client.draft_issue(_bug(), [], final=False))
    return seen[0]


def test_thinking_disabled_sends_enable_thinking_false(monkeypatch):
    """Qwen3 trên DashScope bật thinking sẵn: BUG-107 mất 52.7s (2255/2490 token là reasoning) → timeout."""
    assert _sent_body(monkeypatch, True)["enable_thinking"] is False


def test_thinking_flag_off_sends_nothing(monkeypatch):
    assert "enable_thinking" not in _sent_body(monkeypatch, False)


def test_disable_thinking_default_follows_provider():
    assert config.default_disable_thinking("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "") is True
    assert config.default_disable_thinking("https://api.deepseek.com", "") is False
    assert config.default_disable_thinking("https://api.deepseek.com", "1") is True
    assert config.default_disable_thinking("https://dashscope.aliyuncs.com/compatible-mode/v1", "0") is False


def test_draft_issue_retries_once_on_bad_json(monkeypatch):
    replies = iter(["không phải json", _reply()])
    calls = []

    def handler(request):
        calls.append(1)
        return _ok(next(replies))

    _setup(monkeypatch, handler)
    d = asyncio.run(llm_client.draft_issue(_bug(), [], final=False))
    assert d.status == "ready"
    assert len(calls) == 2


def test_draft_issue_gives_up_after_two_bad_replies(monkeypatch):
    _setup(monkeypatch, lambda request: _ok("vẫn hỏng"))
    with pytest.raises(llm_client.LLMError):
        asyncio.run(llm_client.draft_issue(_bug(), [], final=False))


def test_http_error_raises_llm_error(monkeypatch):
    _setup(monkeypatch, lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(llm_client.LLMError, match="500"):
        asyncio.run(llm_client.draft_issue(_bug(), [], final=False))


def test_timeout_raises_llm_error(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("chậm", request=request)

    _setup(monkeypatch, handler)
    with pytest.raises(llm_client.LLMError):
        asyncio.run(llm_client.draft_issue(_bug(), [], final=False))


def test_odd_response_shape_raises_llm_error(monkeypatch):
    _setup(monkeypatch, lambda request: httpx.Response(200, json={"error": "x"}))
    with pytest.raises(llm_client.LLMError):
        asyncio.run(llm_client.draft_issue(_bug(), [], final=False))
