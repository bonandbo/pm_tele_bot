# GitHub issue từ bug Notion bằng LLM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sau khi bot lưu bug vào Notion, dùng LLM (Qwen/DeepSeek, OpenAI-compatible) chuyển bug thành GitHub issue theo template, chỉ hỏi lại user khi nội dung cốt lõi mơ hồ; đồng thời chuyển ảnh bug sang Notion File Upload + repo GitHub.

**Architecture:** Bốn module mới tách biệt: `issue_models` (dataclass), `issue_template` (dựng markdown, thuần), `llm_client` (gọi LLM, parse JSON), `github_client` (REST). `issue_pipeline` điều phối Notion → LLM → ảnh → GitHub → ghi ngược Notion và không biết gì về Telegram. `bot.py` chỉ thêm state hội thoại, nút, lệnh `/issue`, gọi pipeline.

**Tech Stack:** Python 3.11, python-telegram-bot 21.6 (job-queue), httpx 0.27 (đã có — không thêm thư viện), pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-github-issue-llm-design.md`

## Global Constraints

- Không thêm dependency mới. Gọi mọi API bằng `httpx`, như `notion_client.py`.
- Chạy test bằng: `.venv/Scripts/python.exe -m pytest tests -q` (Windows, từ thư mục repo). Test async dùng `asyncio.run(...)` trong hàm test thường — repo **không** có pytest-asyncio.
- Test không gọi mạng thật: module gọi HTTP có biến `_TRANSPORT = None` truyền vào `httpx.AsyncClient(transport=_TRANSPORT)`; test gắn `httpx.MockTransport`.
- Test import `bot`/`config` cần `.env` có `TELEGRAM_TOKEN`, `NOTION_TOKEN`, `BUG_DB_ID`, `FEATURE_DB_ID` (máy dev đã có).
- Chuỗi hiển thị cho user viết tiếng Việt, cùng giọng với `bot.py`.
- Lỗi LLM/GitHub **không bao giờ** làm hỏng việc lưu Notion hay tin "✅ Đã ghi nhận".
- Thiếu một trong `LLM_API_KEY`, `LLM_MODEL`, `GITHUB_TOKEN`, `GITHUB_REPO` → `config.GITHUB_ENABLED = False` → bot chạy như cũ.
- Không đưa `File.file_path` của Telegram (chứa token bot) vào Notion hay GitHub nữa.
- `MAX_CLARIFY_ROUNDS = 2`, tối đa 3 câu hỏi/vòng, LLM timeout 60s, thử lại 1 lần khi JSON hỏng, ảnh tối đa 5 MB.
- Tên cột Notion mới: `Nhân vật` (Text), `Cấp` (Number), `Bản đồ` (Text), `GitHub Issue` (URL).
- Mọi commit kết thúc bằng dòng: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. **Log user dán có chứa ba dấu backtick** → khung code trong issue không được vỡ; phải dùng fence dài hơn. (Task 1: `test_log_with_backticks_gets_longer_fence`)
2. **LLM trả `questions` là chuỗi thay vì mảng, hoặc `steps` đã đánh số "1. …"** → không được tách từng ký tự thành câu hỏi, không đánh số hai lần, không ăn mất số thập phân đầu bước ("2.5 giây…"). (Task 2: `test_questions_as_string_is_single_question`, `test_steps_string_split_and_numbering_removed`, `test_step_starting_with_decimal_is_kept`)
3. **Bug cũ tạo trước khi thêm cột** (không có `Nhân vật`/`Cấp`/`GitHub Issue`, ảnh là link Telegram đã chết) → `/issue` và nút Bổ sung vẫn chạy, ảnh chết chỉ bị đếm "không tải được". (Task 5: `test_bug_from_old_page_missing_new_columns`, `test_publish_image_failure_is_counted`)
4. **User nhắn thêm trong lúc bot đang soạn issue** → không được tạo bug trùng; bot trả "đang xử lý". (Task 8: `test_conversation_has_waiting_state_and_nonblocking_slow_handlers`)
5. **Bấm Severity/Module trên thẻ group sau khi bot đã gắn nút Bổ sung/GitHub** → nút đó không được biến mất. (Task 9: `test_clarify_button_url_found`, `test_bug_card_buttons`)

## File Structure

| File | Trạng thái | Trách nhiệm |
|---|---|---|
| `issue_models.py` | mới | `BugInput`, `IssueFields`, `Draft`, `DOMAINS` |
| `issue_template.py` | mới | `render_title`, `render_body` (thuần) |
| `llm_client.py` | mới | `build_messages`, `parse_draft` (thuần), `draft_issue` (mạng), `LLMError` |
| `github_client.py` | mới | `create_issue`, `put_asset`, `asset_url`, `GitHubError` |
| `issue_pipeline.py` | mới | `enabled`, `bug_from_page`, `load_bug`, `draft`, `publish`, `PipelineError` |
| `config.py` | sửa | biến LLM/GitHub, `GITHUB_ENABLED`, 4 prop mới trong `BUG_PROPS` |
| `notion_client.py` | sửa | upload ảnh, prop mới, `set_github_issue`, `read_bug_body`, `parse_bug_blocks` |
| `bot.py` | sửa | ảnh bytes, 3 bước mới, luồng GitHub, deep-link clarify, `/issue`, WAITING |
| `README.md`, `.env.example`, `env.example.txt` | sửa | hướng dẫn cài đặt |
| `tests/test_issue_template.py`, `tests/test_llm_client.py`, `tests/test_github_client.py`, `tests/test_notion_bug.py`, `tests/test_issue_pipeline.py`, `tests/test_bot_github.py`, `tests/notion_fixtures.py` | mới | test |

---

### Task 1: Kiểu dữ liệu + dựng template issue

**Files:**
- Create: `issue_models.py`
- Create: `issue_template.py`
- Test: `tests/test_issue_template.py`

**Interfaces:**
- Consumes: không
- Produces:
  - `issue_models.DOMAINS: tuple[str, ...]` = `("client", "server", "config", "data", "websdk")`
  - `issue_models.BugInput(page_id, bug_id, notion_url, title, description="", steps="", severity="", version="", modules="", character="", level: Optional[int]=None, map_name="", images: list[tuple[str, str]]=[], github_issue="")`
  - `issue_models.IssueFields(title, symptom, steps: list[str]=[], log="", domain="")`
  - `issue_models.Draft(status: str, questions: list[str], issue: IssueFields)`
  - `issue_template.render_title(bug: BugInput, fields: IssueFields) -> str`
  - `issue_template.render_body(bug: BugInput, fields: IssueFields, image_links: list[str], failed_images: int = 0) -> str`

- [ ] **Step 1: Viết `issue_models.py`** (chỉ dataclass, không có logic để test riêng)

```python
"""Kiểu dữ liệu dùng chung cho luồng tạo GitHub issue từ bug Notion."""
from dataclasses import dataclass, field
from typing import Optional

# Miền nghi ngờ hợp lệ trong template issue
DOMAINS = ("client", "server", "config", "data", "websdk")


@dataclass
class BugInput:
    """Bug đọc từ Notion — đầu vào cho LLM và template."""
    page_id: str
    bug_id: str                 # "BUG-12"
    notion_url: str
    title: str
    description: str = ""
    steps: str = ""
    severity: str = ""
    version: str = ""
    modules: str = ""
    character: str = ""
    level: Optional[int] = None
    map_name: str = ""
    images: list[tuple[str, str]] = field(default_factory=list)  # (block_id, url tải được)
    github_issue: str = ""      # URL issue đã tạo, "" nếu chưa


@dataclass
class IssueFields:
    """Các trường LLM điền cho issue."""
    title: str
    symptom: str
    steps: list[str] = field(default_factory=list)
    log: str = ""
    domain: str = ""            # "" hoặc một giá trị trong DOMAINS


@dataclass
class Draft:
    status: str                 # "ready" | "need_info"
    questions: list[str]
    issue: IssueFields          # luôn có — bản nháp tốt nhất
```

- [ ] **Step 2: Viết test cho template**

`tests/test_issue_template.py`:

````python
"""Test dựng tiêu đề + body GitHub issue (thuần, không mạng)."""
from issue_models import BugInput, IssueFields
from issue_template import render_body, render_title


def _bug(**kw) -> BugInput:
    base = dict(
        page_id="p1", bug_id="BUG-12", notion_url="https://www.notion.so/p1",
        title="Rớt mạng", severity="Cao", version="v1.2", modules="Server",
        character="Thiếu Lâm", level=90, map_name="Tương Dương",
    )
    base.update(kw)
    return BugInput(**base)


def _fields(**kw) -> IssueFields:
    base = dict(
        title="Rớt kết nối khi vào Tống Kim", symptom="Client bị disconnect.",
        steps=["Vào Tống Kim", "Chờ loading"], log="", domain="server",
    )
    base.update(kw)
    return IssueFields(**base)


def test_title_has_bug_id_prefix():
    assert render_title(_bug(), _fields()) == "[BUG-12] Rớt kết nối khi vào Tống Kim"


def test_title_falls_back_to_notion_title():
    assert render_title(_bug(), _fields(title="  ")) == "[BUG-12] Rớt mạng"


def test_title_is_capped():
    assert len(render_title(_bug(), _fields(title="x" * 500))) == 200


def test_full_body_sections_in_order():
    body = render_body(_bug(), _fields(), [])
    order = ["## Triệu chứng", "## Cách tái hiện", "## Môi trường",
             "## Log liên quan", "## Nghi ngờ thuộc miền nào"]
    idx = [body.index(h) for h in order]
    assert idx == sorted(idx)
    assert body.startswith("> BUG-12 · Cao · v1.2 · Server · [Notion](https://www.notion.so/p1)\n")
    assert "1. Vào Tống Kim\n2. Chờ loading" in body
    assert "- Nhân vật + cấp: Thiếu Lâm 90" in body
    assert "- Bản đồ: Tương Dương" in body
    assert body.rstrip().endswith("server")
    assert "Máy" not in body


def test_empty_fields_show_placeholders():
    bug = _bug(severity="", version="", modules="", character="", level=None, map_name="")
    body = render_body(bug, _fields(steps=[], domain="", symptom=""), [])
    assert body.startswith("> BUG-12 · [Notion](")
    assert "## Triệu chứng\n_(chưa rõ)_" in body
    assert "## Cách tái hiện\n_(chưa rõ)_" in body
    assert "- Nhân vật + cấp: _(chưa rõ)_" in body
    assert "- Bản đồ: _(chưa rõ)_" in body
    assert "## Log liên quan\n_(không có)_" in body
    assert body.endswith("## Nghi ngờ thuộc miền nào\n")


def test_level_without_character():
    body = render_body(_bug(character=""), _fields(), [])
    assert "- Nhân vật + cấp: 90" in body


def test_images_under_symptom_and_failed_note():
    body = render_body(_bug(), _fields(), ["https://x/1.jpg", "https://x/2.jpg"], failed_images=1)
    sym = body.index("## Triệu chứng")
    rep = body.index("## Cách tái hiện")
    one = body.index("![BUG-12 ảnh 1](https://x/1.jpg)")
    two = body.index("![BUG-12 ảnh 2](https://x/2.jpg)")
    assert sym < one < two < rep
    assert "_(1 ảnh không tải được — xem trên Notion)_" in body


def test_log_is_fenced():
    body = render_body(_bug(), _fields(log="NullReferenceException at X"), [])
    assert "```\nNullReferenceException at X\n```" in body


def test_log_with_backticks_gets_longer_fence():
    body = render_body(_bug(), _fields(log="lỗi ```code``` ở đây"), [])
    assert "````\nlỗi ```code``` ở đây\n````" in body
````

- [ ] **Step 3: Chạy test, xác nhận FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_issue_template.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'issue_template'`

- [ ] **Step 4: Viết `issue_template.py`**

```python
"""Dựng tiêu đề + body GitHub issue theo template bug — hàm thuần, không gọi mạng."""
import re

from issue_models import BugInput, IssueFields

UNKNOWN = "_(chưa rõ)_"
NO_LOG = "_(không có)_"
_TITLE_MAX = 200


def render_title(bug: BugInput, fields: IssueFields) -> str:
    title = (fields.title or "").strip() or bug.title.strip()
    return f"[{bug.bug_id}] {title}"[:_TITLE_MAX]


def _fence(text: str) -> str:
    """Code fence dài hơn mọi chuỗi backtick trong text để log không phá khung."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    tick = "`" * max(3, longest + 1)
    return f"{tick}\n{text}\n{tick}"


def render_body(
    bug: BugInput,
    fields: IssueFields,
    image_links: list[str],
    failed_images: int = 0,
) -> str:
    head = " · ".join(x for x in (bug.bug_id, bug.severity, bug.version, bug.modules) if x)
    lines = [f"> {head} · [Notion]({bug.notion_url})", ""]

    lines += ["## Triệu chứng", fields.symptom.strip() or UNKNOWN]
    for i, link in enumerate(image_links, 1):
        lines += ["", f"![{bug.bug_id} ảnh {i}]({link})"]
    if failed_images:
        lines += ["", f"_({failed_images} ảnh không tải được — xem trên Notion)_"]

    steps = [s.strip() for s in fields.steps if s.strip()]
    lines += ["", "## Cách tái hiện"]
    lines += [f"{i}. {s}" for i, s in enumerate(steps, 1)] or [UNKNOWN]

    who = " ".join(x for x in (bug.character, str(bug.level) if bug.level else "") if x)
    lines += [
        "", "## Môi trường",
        f"- Nhân vật + cấp: {who or UNKNOWN}",
        f"- Bản đồ: {bug.map_name or UNKNOWN}",
    ]

    log_text = fields.log.strip()
    lines += ["", "## Log liên quan", _fence(log_text) if log_text else NO_LOG]
    lines += ["", "## Nghi ngờ thuộc miền nào", fields.domain]
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS (18 cũ + 10 mới)

- [ ] **Step 6: Commit**

```bash
git add issue_models.py issue_template.py tests/test_issue_template.py
git commit -m "Thêm model + template GitHub issue cho bug

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: LLM client

**Files:**
- Modify: `config.py` (cuối file)
- Create: `llm_client.py`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `issue_models.BugInput`, `IssueFields`, `Draft`, `DOMAINS` (Task 1)
- Produces:
  - `config.LLM_BASE_URL: str`, `config.LLM_API_KEY: str`, `config.LLM_MODEL: str`
  - `llm_client.LLMError(Exception)`
  - `llm_client.FINAL_NOTE: str`, `llm_client.MAX_QUESTIONS = 3`
  - `llm_client.build_messages(bug: BugInput, qa: list[tuple[str, str]], final: bool) -> list[dict]`
  - `llm_client.parse_draft(text: str, fallback_title: str) -> Draft`
  - `async llm_client.draft_issue(bug: BugInput, qa: list[tuple[str, str]], final: bool) -> Draft` — thử lại 1 lần khi JSON hỏng; lỗi mạng/HTTP/JSON → `LLMError`

- [ ] **Step 1: Thêm cấu hình LLM vào cuối `config.py`**

```python

# ---- LLM (OpenAI-compatible: DashScope/Qwen, DeepSeek) — tạo GitHub issue ----
# DashScope quốc tế: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
# DeepSeek:          https://api.deepseek.com
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
).strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip()
```

- [ ] **Step 2: Viết test**

`tests/test_llm_client.py`:

````python
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
````

- [ ] **Step 3: Chạy test, xác nhận FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm_client'`

- [ ] **Step 4: Viết `llm_client.py`**

```python
"""Gọi LLM (OpenAI-compatible: DashScope/Qwen, DeepSeek) để chuyển bug thành các trường GitHub issue."""
import json
import logging
import re

import httpx

import config
from issue_models import DOMAINS, BugInput, Draft, IssueFields

log = logging.getLogger(__name__)

MAX_QUESTIONS = 3
_TIMEOUT = 60
_TRANSPORT = None  # test gắn httpx.MockTransport

FINAL_NOTE = "Đây là lượt cuối: bắt buộc status=ready, không hỏi thêm."

SYSTEM_PROMPT = """Bạn chuyển báo cáo bug của game Võ Lâm Truyền Kỳ (VLTK) thành GitHub issue để một AI agent lập trình đọc và sửa.

Trả về DUY NHẤT một object JSON đúng dạng:
{"status": "ready" hoặc "need_info",
 "questions": ["..."],
 "issue": {"title": "...", "symptom": "...", "steps": ["..."], "log": "...", "domain": "..."}}

Ý nghĩa các trường trong issue:
- title: tiêu đề ngắn (dưới 80 ký tự), nêu đúng hiện tượng.
- symptom: người chơi nhìn thấy gì, sai ở đâu, khác kỳ vọng thế nào.
- steps: các bước tái hiện, mỗi phần tử một bước, không đánh số.
- log: chỉ chép nguyên văn đoạn log / thông báo lỗi mà user thực sự đã dán. Không có thì "".
- domain: một trong client, server, config, data, websdk — chỉ điền khi thông tin chỉ rõ, không chắc thì "".
  client = hiển thị, UI, thao tác trên máy người chơi;
  server = logic game, đồng bộ, rớt kết nối, tính toán phía máy chủ;
  config = file cấu hình, thông số cân bằng;
  data = dữ liệu vật phẩm / NPC / nhiệm vụ / bản đồ bị sai;
  websdk = đăng nhập, nạp thẻ, trang web.

Quy tắc:
- Không bịa thông tin không có trong báo cáo. Viết tiếng Việt, gọn, rõ.
- Chỉ đặt status = "need_info" khi: (1) không hiểu được hiện tượng sai là gì; hoặc (2) người khác đọc các bước không thể tái hiện; hoặc (3) các thông tin mâu thuẫn nhau.
- KHÔNG hỏi về nhân vật, cấp, bản đồ, máy, log hay miền nghi ngờ.
- Khi need_info: tối đa 3 câu hỏi ngắn, cụ thể. Khi ready: questions = [].
- Luôn điền "issue" với bản nháp tốt nhất có thể, kể cả khi need_info."""


class LLMError(Exception):
    """Lỗi gọi LLM hoặc LLM trả dữ liệu không dùng được. Message hiện được cho user."""


def build_messages(bug: BugInput, qa: list[tuple[str, str]], final: bool) -> list[dict]:
    parts = [
        f"Tiêu đề: {bug.title}",
        f"Mô tả:\n{bug.description or '(trống)'}",
        f"Bước tái hiện:\n{bug.steps or '(trống)'}",
    ]
    meta = ", ".join(
        f"{k}: {v}"
        for k, v in (("Severity", bug.severity), ("Version", bug.version), ("Module", bug.modules))
        if v
    )
    if meta:
        parts.append(meta)
    for question, answer in qa:
        parts.append(f"Bot đã hỏi:\n{question}\nUser trả lời:\n{answer}")
    if final:
        parts.append(FINAL_NOTE)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


_FENCE_RE = re.compile(r"^`{3}(?:json)?\s*(.*?)\s*`{3}$", re.DOTALL | re.IGNORECASE)
# "1. ", "2) ", "- ", "• " ở đầu bước — bắt buộc có khoảng trắng sau để không ăn "2.5 giây"
_STEP_PREFIX_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")


def _clean_steps(raw) -> list[str]:
    if isinstance(raw, str):
        raw = raw.splitlines()
    if not isinstance(raw, list):
        return []
    steps = [_STEP_PREFIX_RE.sub("", str(s)).strip() for s in raw]
    return [s for s in steps if s]


def _clean_questions(raw) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(q).strip() for q in raw if str(q).strip()][:MAX_QUESTIONS]


def parse_draft(text: str, fallback_title: str) -> Draft:
    raw = (text or "").strip()
    m = _FENCE_RE.match(raw)
    if m:
        raw = m.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM trả JSON hỏng ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise LLMError("LLM không trả object JSON")

    status = data.get("status")
    if status not in ("ready", "need_info"):
        raise LLMError(f"LLM trả status không hợp lệ: {status!r}")

    issue = data.get("issue")
    if not isinstance(issue, dict):
        issue = {}
    domain = str(issue.get("domain") or "").strip().lower()
    fields = IssueFields(
        title=str(issue.get("title") or "").strip() or fallback_title,
        symptom=str(issue.get("symptom") or "").strip(),
        steps=_clean_steps(issue.get("steps")),
        log=str(issue.get("log") or "").strip(),
        domain=domain if domain in DOMAINS else "",
    )

    questions = _clean_questions(data.get("questions"))
    if status == "need_info" and not questions:
        status = "ready"
    if status == "ready":
        questions = []
    return Draft(status=status, questions=questions, issue=fields)


async def _chat(messages: list[dict]) -> str:
    url = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
    body = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=_TRANSPORT) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise LLMError(f"Không gọi được LLM ({exc.__class__.__name__})") from exc
    if resp.status_code >= 400:
        log.error("LLM lỗi %s: %s", resp.status_code, resp.text[:500])
        raise LLMError(f"LLM trả lỗi HTTP {resp.status_code}")
    try:
        return resp.json()["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("LLM trả dữ liệu không đúng định dạng") from exc


async def draft_issue(bug: BugInput, qa: list[tuple[str, str]], final: bool) -> Draft:
    """Một vòng LLM. JSON hỏng thì thử lại 1 lần rồi mới ném LLMError."""
    messages = build_messages(bug, qa, final)
    last_err: LLMError | None = None
    for attempt in range(2):
        text = await _chat(messages)
        try:
            return parse_draft(text, bug.title)
        except LLMError as exc:
            log.warning("LLM trả JSON không dùng được (lần %d): %s", attempt + 1, exc)
            last_err = exc
    raise last_err
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS

- [ ] **Step 6: Commit**

```bash
git add config.py llm_client.py tests/test_llm_client.py
git commit -m "Thêm llm_client: chuyển bug thành trường issue qua LLM OpenAI-compatible

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: GitHub client

**Files:**
- Modify: `config.py` (cuối file)
- Create: `github_client.py`
- Test: `tests/test_github_client.py`

**Interfaces:**
- Consumes: `config.LLM_API_KEY`, `config.LLM_MODEL` (Task 2)
- Produces:
  - `config.GITHUB_TOKEN: str`, `config.GITHUB_REPO: str`, `config.GITHUB_LABELS: list[str]`, `config.GITHUB_ASSETS_BRANCH: str`, `config.GITHUB_ENABLED: bool`
  - `github_client.GitHubError(Exception)`
  - `async github_client.create_issue(title: str, body: str, labels: list[str]) -> tuple[int, str]` — `(number, html_url)`
  - `github_client.asset_url(path: str) -> str`
  - `async github_client.put_asset(path: str, data: bytes, message: str) -> str` — URL nhúng ảnh; file đã có → dùng lại

- [ ] **Step 1: Thêm cấu hình GitHub vào cuối `config.py`**

```python

# ---- GitHub issue cho AI agent ----
# Token fine-grained, chỉ 1 repo, quyền Issues: write + Contents: write.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()          # owner/repo
GITHUB_LABELS = [
    x.strip() for x in os.getenv("GITHUB_LABELS", "bug").split(",") if x.strip()
]
# Branch riêng chứa ảnh bug — tạo tay 1 lần (xem README)
GITHUB_ASSETS_BRANCH = os.getenv("GITHUB_ASSETS_BRANCH", "bug-assets").strip()

# Thiếu bất kỳ biến nào → tắt tính năng, bot chạy như cũ
GITHUB_ENABLED = all([LLM_API_KEY, LLM_MODEL, GITHUB_TOKEN, GITHUB_REPO])
```

- [ ] **Step 2: Viết test**

`tests/test_github_client.py`:

```python
"""Test github_client với httpx.MockTransport (không gọi GitHub thật)."""
import asyncio
import base64
import json

import httpx
import pytest

import config
import github_client


def _setup(monkeypatch, handler):
    monkeypatch.setattr(github_client, "_TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setattr(config, "GITHUB_TOKEN", "ghp_test")
    monkeypatch.setattr(config, "GITHUB_REPO", "team/game")
    monkeypatch.setattr(config, "GITHUB_ASSETS_BRANCH", "bug-assets")


ASSET = "https://github.com/team/game/blob/bug-assets/bug-assets/BUG-1/a.jpg?raw=true"


def test_create_issue_posts_title_body_labels(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"number": 34, "html_url": "https://github.com/team/game/issues/34"})

    _setup(monkeypatch, handler)
    result = asyncio.run(github_client.create_issue("[BUG-1] T", "body", ["bug"]))
    assert result == (34, "https://github.com/team/game/issues/34")
    req = seen[0]
    assert req.method == "POST"
    assert req.url.path == "/repos/team/game/issues"
    assert req.headers["authorization"] == "Bearer ghp_test"
    assert json.loads(req.content) == {"title": "[BUG-1] T", "body": "body", "labels": ["bug"]}


def test_create_issue_error_raises(monkeypatch):
    _setup(monkeypatch, lambda request: httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(github_client.GitHubError, match="404"):
        asyncio.run(github_client.create_issue("t", "b", []))


def test_create_issue_network_error_raises(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    _setup(monkeypatch, handler)
    with pytest.raises(github_client.GitHubError):
        asyncio.run(github_client.create_issue("t", "b", []))


def test_asset_url(monkeypatch):
    _setup(monkeypatch, lambda r: httpx.Response(200))
    assert github_client.asset_url("bug-assets/BUG-1/a.jpg") == ASSET


def test_put_asset_commits_base64_to_branch(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"content": {}})

    _setup(monkeypatch, handler)
    url = asyncio.run(github_client.put_asset("bug-assets/BUG-1/a.jpg", b"img", "BUG-1: ảnh"))
    assert url == ASSET
    req = seen[0]
    assert req.method == "PUT"
    assert req.url.path == "/repos/team/game/contents/bug-assets/BUG-1/a.jpg"
    body = json.loads(req.content)
    assert base64.b64decode(body["content"]) == b"img"
    assert body["branch"] == "bug-assets"
    assert body["message"] == "BUG-1: ảnh"


def test_put_asset_existing_file_is_reused(monkeypatch):
    def handler(request):
        if request.method == "PUT":
            return httpx.Response(422, json={"message": "\"sha\" wasn't supplied."})
        assert request.url.params["ref"] == "bug-assets"
        return httpx.Response(200, json={"sha": "abc"})

    _setup(monkeypatch, handler)
    assert asyncio.run(github_client.put_asset("bug-assets/BUG-1/a.jpg", b"img", "m")) == ASSET


def test_put_asset_422_without_existing_file_raises(monkeypatch):
    def handler(request):
        if request.method == "PUT":
            return httpx.Response(422, json={"message": "Branch not found"})
        return httpx.Response(404)

    _setup(monkeypatch, handler)
    with pytest.raises(github_client.GitHubError, match="422"):
        asyncio.run(github_client.put_asset("bug-assets/BUG-1/a.jpg", b"img", "m"))
```

- [ ] **Step 3: Chạy test, xác nhận FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_github_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'github_client'`

- [ ] **Step 4: Viết `github_client.py`**

```python
"""Lớp bọc GitHub REST — tạo issue, commit ảnh bug vào branch assets."""
import base64
import logging

import httpx

import config

log = logging.getLogger(__name__)

_API = "https://api.github.com"
_TRANSPORT = None  # test gắn httpx.MockTransport


class GitHubError(Exception):
    """Lỗi gọi GitHub. Message hiện được cho user."""


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=30, transport=_TRANSPORT) as client:
            return await client.request(method, f"{_API}{path}", headers=_headers(), **kwargs)
    except httpx.HTTPError as exc:
        raise GitHubError(f"Không gọi được GitHub ({exc.__class__.__name__})") from exc


async def create_issue(title: str, body: str, labels: list[str]) -> tuple[int, str]:
    resp = await _request("POST", f"/repos/{config.GITHUB_REPO}/issues", json={
        "title": title, "body": body, "labels": labels,
    })
    if resp.status_code >= 400:
        log.error("GitHub tạo issue lỗi %s: %s", resp.status_code, resp.text[:500])
        raise GitHubError(f"GitHub trả lỗi HTTP {resp.status_code} khi tạo issue")
    data = resp.json()
    return data["number"], data["html_url"]


def asset_url(path: str) -> str:
    """Link nhúng ảnh trong issue. Repo private → chỉ người có quyền vào repo xem được."""
    return f"https://github.com/{config.GITHUB_REPO}/blob/{config.GITHUB_ASSETS_BRANCH}/{path}?raw=true"


async def put_asset(path: str, data: bytes, message: str) -> str:
    repo, branch = config.GITHUB_REPO, config.GITHUB_ASSETS_BRANCH
    resp = await _request("PUT", f"/repos/{repo}/contents/{path}", json={
        "message": message,
        "content": base64.b64encode(data).decode("ascii"),
        "branch": branch,
    })
    if resp.status_code == 422:
        # Thường là file đã tồn tại (chạy lại sau lỗi) → có rồi thì dùng lại
        check = await _request("GET", f"/repos/{repo}/contents/{path}", params={"ref": branch})
        if check.status_code == 200:
            log.info("Ảnh %s đã có trên GitHub, dùng lại", path)
            return asset_url(path)
    if resp.status_code >= 400:
        log.error("GitHub upload ảnh lỗi %s: %s", resp.status_code, resp.text[:500])
        raise GitHubError(f"GitHub trả lỗi HTTP {resp.status_code} khi upload ảnh")
    return asset_url(path)
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS

- [ ] **Step 6: Commit**

```bash
git add config.py github_client.py tests/test_github_client.py
git commit -m "Thêm github_client: tạo issue, commit ảnh vào branch assets

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Notion — cột mới, upload ảnh, đọc body bug

**Files:**
- Modify: `config.py` (`BUG_PROPS`)
- Modify: `notion_client.py` (`_request`, `_plain`, `create_bug`, `create_feature`; thêm hàm mới)
- Test: `tests/test_notion_bug.py`

**Interfaces:**
- Consumes: không
- Produces:
  - `config.BUG_PROPS["character" | "level" | "map" | "github_issue"]` = `"Nhân vật" | "Cấp" | "Bản đồ" | "GitHub Issue"`
  - `notion_client._TRANSPORT = None`
  - `notion_client._plain` đọc thêm kiểu `number` (→ `"90"`) và `url`
  - `notion_client.Image = tuple[bytes, str, str]` — `(data, filename, content_type)`
  - `async notion_client.upload_file(data: bytes, filename: str, content_type: str) -> str` (file_upload id)
  - `async notion_client.create_bug(*, title, description, steps="", severity=None, priority=None, version_found=None, modules=None, reporter="", telegram_id="", character="", level: Optional[int]=None, map_name="", images: Optional[list[Image]]=None) -> dict` — **thay** `image_urls` bằng `images`
  - `async notion_client.create_feature(..., images: Optional[list[Image]]=None)` — **thay** `image_urls`
  - `async notion_client.set_github_issue(page_id: str, url: str) -> dict`
  - `notion_client.parse_bug_blocks(blocks: list[dict]) -> tuple[str, str, list[tuple[str, str]]]` — `(description, steps, [(block_id, url)])`
  - `async notion_client.read_bug_body(page_id: str) -> tuple[str, str, list[tuple[str, str]]]`

- [ ] **Step 1: Thêm 4 cột vào `BUG_PROPS` trong `config.py`**

Sửa khối `BUG_PROPS`, thêm 4 dòng trước dấu `}`:

```python
    "reporter": "Người báo cáo",
    "telegram_id": "Telegram ID",
    "character": "Nhân vật",
    "level": "Cấp",
    "map": "Bản đồ",
    "github_issue": "GitHub Issue",
}
```

- [ ] **Step 2: Viết test**

`tests/test_notion_bug.py`:

```python
"""Test phần Notion cho luồng GitHub: prop mới, upload ảnh, đọc body (không gọi Notion thật)."""
import asyncio
import json

import httpx

import config
import notion_client as nc

P = config.BUG_PROPS


def _rt(text):
    return [{"plain_text": text, "type": "text", "text": {"content": text}}]


def test_plain_reads_number_and_url():
    assert nc._plain({"type": "number", "number": 90}) == "90"
    assert nc._plain({"type": "number", "number": None}) == ""
    assert nc._plain({"type": "url", "url": "https://x"}) == "https://x"
    assert nc._plain({"type": "url", "url": None}) == ""


def test_parse_bug_blocks():
    blocks = [
        {"id": "h1", "type": "heading_2", "heading_2": {"rich_text": _rt("Mô tả")}},
        {"id": "a", "type": "paragraph", "paragraph": {"rich_text": _rt("dòng 1")}},
        {"id": "b", "type": "paragraph", "paragraph": {"rich_text": _rt("dòng 2")}},
        {"id": "h2", "type": "heading_2", "heading_2": {"rich_text": _rt("Bước tái hiện")}},
        {"id": "c", "type": "paragraph", "paragraph": {"rich_text": _rt("b1")}},
        {"id": "h3", "type": "heading_2", "heading_2": {"rich_text": _rt("Ảnh / Video")}},
        {"id": "img1", "type": "image",
         "image": {"type": "file", "file": {"url": "https://s3/x.jpg", "expiry_time": "t"}}},
        {"id": "img2", "type": "image",
         "image": {"type": "external", "external": {"url": "https://ext/y.png"}}},
        {"id": "h4", "type": "heading_2", "heading_2": {"rich_text": _rt(nc.HISTORY_HEADING)}},
        {"id": "d", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt("Tạo bug")}},
        {"id": "e", "type": "paragraph", "paragraph": {"rich_text": _rt("không thuộc mục nào")}},
    ]
    desc, steps, images = nc.parse_bug_blocks(blocks)
    assert desc == "dòng 1\ndòng 2"
    assert steps == "b1"
    assert images == [("img1", "https://s3/x.jpg"), ("img2", "https://ext/y.png")]


def test_parse_bug_blocks_empty():
    assert nc.parse_bug_blocks([]) == ("", "", [])


def _mock(monkeypatch, handler):
    monkeypatch.setattr(nc, "_TRANSPORT", httpx.MockTransport(handler))


def test_upload_file_creates_then_sends_multipart(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/file_uploads":
            return httpx.Response(200, json={"id": "fu1", "status": "pending"})
        return httpx.Response(200, json={"id": "fu1", "status": "uploaded"})

    _mock(monkeypatch, handler)
    assert asyncio.run(nc.upload_file(b"img", "a.jpg", "image/jpeg")) == "fu1"
    create, send = seen
    assert json.loads(create.content) == {"filename": "a.jpg", "content_type": "image/jpeg"}
    assert send.url.path == "/v1/file_uploads/fu1/send"
    assert send.headers["content-type"].startswith("multipart/form-data")
    assert b"img" in send.content


def test_create_bug_sets_new_props_and_image_block(monkeypatch):
    pages = []

    def handler(request):
        path = request.url.path
        if path == "/v1/file_uploads":
            return httpx.Response(200, json={"id": "fu1"})
        if path.endswith("/send"):
            return httpx.Response(200, json={"status": "uploaded"})
        pages.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "p1", "properties": {}})

    _mock(monkeypatch, handler)
    asyncio.run(nc.create_bug(
        title="T", description="D", character="Thiếu Lâm", level=90, map_name="Tương Dương",
        images=[(b"img", "a.jpg", "image/jpeg")],
    ))
    body = pages[0]
    props = body["properties"]
    assert props[P["character"]]["rich_text"][0]["text"]["content"] == "Thiếu Lâm"
    assert props[P["level"]] == {"number": 90}
    assert props[P["map"]]["rich_text"][0]["text"]["content"] == "Tương Dương"
    image_blocks = [b for b in body["children"] if b["type"] == "image"]
    assert image_blocks == [{
        "object": "block", "type": "image",
        "image": {"type": "file_upload", "file_upload": {"id": "fu1"}},
    }]
    assert "api.telegram.org" not in json.dumps(body)


def test_create_bug_without_level_sends_null_number(monkeypatch):
    pages = []

    def handler(request):
        pages.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "p1", "properties": {}})

    _mock(monkeypatch, handler)
    asyncio.run(nc.create_bug(title="T", description="D"))
    assert pages[0]["properties"][P["level"]] == {"number": None}
    assert not [b for b in pages[0]["children"] if b["type"] == "image"]


def test_create_bug_survives_upload_failure(monkeypatch):
    pages = []

    def handler(request):
        if request.url.path.startswith("/v1/file_uploads"):
            return httpx.Response(500, json={"message": "boom"})
        pages.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "p1", "properties": {}})

    _mock(monkeypatch, handler)
    asyncio.run(nc.create_bug(title="T", description="D", images=[(b"img", "a.jpg", "image/jpeg")]))
    assert len(pages) == 1
    assert not [b for b in pages[0]["children"] if b["type"] == "image"]


def test_set_github_issue(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "p1"})

    _mock(monkeypatch, handler)
    asyncio.run(nc.set_github_issue("p1", "https://github.com/t/g/issues/34"))
    req = seen[0]
    assert req.method == "PATCH" and req.url.path == "/v1/pages/p1"
    assert json.loads(req.content) == {
        "properties": {P["github_issue"]: {"url": "https://github.com/t/g/issues/34"}}
    }


def test_read_bug_body_pages_through_children(monkeypatch):
    def handler(request):
        if "start_cursor" not in request.url.params:
            return httpx.Response(200, json={
                "results": [{"id": "h", "type": "heading_2", "heading_2": {"rich_text": _rt("Mô tả")}}],
                "has_more": True, "next_cursor": "c2",
            })
        return httpx.Response(200, json={
            "results": [{"id": "a", "type": "paragraph", "paragraph": {"rich_text": _rt("mô tả")}}],
            "has_more": False,
        })

    _mock(monkeypatch, handler)
    assert asyncio.run(nc.read_bug_body("p1")) == ("mô tả", "", [])
```

- [ ] **Step 3: Chạy test, xác nhận FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_notion_bug.py -q`
Expected: FAIL — `AttributeError: module 'notion_client' has no attribute '_TRANSPORT'` / `parse_bug_blocks` / tham số `character` không tồn tại

- [ ] **Step 4: Sửa `_request` để có `_TRANSPORT` và gửi được multipart**

Trong `notion_client.py`, ngay dưới `_MAX_QUERY = 500` thêm:

```python

_TRANSPORT = None  # test gắn httpx.MockTransport
```

Thay thân `_request` thành:

```python
async def _request(method: str, path: str, **kwargs) -> dict[str, Any]:
    url = f"{config.NOTION_API}{path}"
    headers = dict(_HEADERS)
    if "files" in kwargs:
        # multipart: để httpx tự đặt Content-Type kèm boundary
        headers.pop("Content-Type")
    async with _sem:
        async with httpx.AsyncClient(timeout=30, transport=_TRANSPORT) as client:
            for attempt in range(3):
                resp = await client.request(method, url, headers=headers, **kwargs)
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", 1))
                    log.warning("Notion rate limit, chờ %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code >= 400:
                    log.error("Notion API lỗi %s: %s", resp.status_code, resp.text[:500])
                    resp.raise_for_status()
                return resp.json()
    raise RuntimeError("Notion API: hết lượt retry sau khi bị rate limit")
```

- [ ] **Step 5: `_plain` đọc `number` và `url`; thêm helper**

Trong `_plain`, ngay trước dòng `if t == "created_time":` thêm:

```python
    if t == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    if t == "url":
        return prop.get("url") or ""
```

Dưới hàm `_title` thêm:

```python
def _number(value: Optional[int]) -> dict:
    return {"number": value}
```

- [ ] **Step 6: Upload ảnh + sửa `create_bug` / `create_feature`**

Thêm ngay trên `# ---------------------------------------------------------------- create`:

```python
# ---------------------------------------------------------------- upload ảnh

# (data, filename, content_type)
Image = tuple[bytes, str, str]


async def upload_file(data: bytes, filename: str, content_type: str) -> str:
    """Notion File Upload API (single part). Trả file_upload id để gắn vào block trong 1 giờ."""
    created = await _request("POST", "/file_uploads", json={
        "filename": filename, "content_type": content_type,
    })
    upload_id = created["id"]
    await _request(
        "POST", f"/file_uploads/{upload_id}/send",
        files={"file": (filename, data, content_type)},
    )
    return upload_id


async def _image_blocks(images: Optional[list[Image]]) -> list[dict]:
    """Upload từng ảnh lên Notion. Ảnh lỗi bị bỏ qua — không làm hỏng việc tạo page."""
    blocks = []
    for data, filename, content_type in images or []:
        try:
            upload_id = await upload_file(data, filename, content_type)
        except Exception:
            log.exception("Upload ảnh lên Notion thất bại: %s", filename)
            continue
        blocks.append({
            "object": "block",
            "type": "image",
            "image": {"type": "file_upload", "file_upload": {"id": upload_id}},
        })
    return blocks
```

Thay toàn bộ `create_bug` bằng:

```python
async def create_bug(
    *,
    title: str,
    description: str,
    steps: str = "",
    severity: Optional[str] = None,
    priority: Optional[str] = None,
    version_found: Optional[str] = None,
    modules: Optional[list[str]] = None,
    reporter: str = "",
    telegram_id: str = "",
    character: str = "",
    level: Optional[int] = None,
    map_name: str = "",
    images: Optional[list[Image]] = None,
) -> dict[str, Any]:
    p = config.BUG_PROPS
    props = {
        p["title"]: _title(title),
        p["status"]: _select("Mới báo cáo"),
        p["severity"]: _select(severity),
        p["priority"]: _select(priority),
        p["version_found"]: _select(version_found),
        p["module"]: _multi_select(modules),
        p["reporter"]: _rich_text(reporter),
        p["telegram_id"]: _rich_text(telegram_id),
        p["character"]: _rich_text(character),
        p["level"]: _number(level),
        p["map"]: _rich_text(map_name),
    }

    children = _text_block("heading_2", "Mô tả") + _paragraphs(description)
    if steps:
        children += _text_block("heading_2", "Bước tái hiện") + _paragraphs(steps)
    image_blocks = await _image_blocks(images)
    if image_blocks:
        children += _text_block("heading_2", "Ảnh / Video") + image_blocks
    children += _text_block("heading_2", HISTORY_HEADING)
    children += _history_item(f"Tạo bug · Mới báo cáo · bởi {reporter or '?'}")

    return await _request("POST", "/pages", json={
        "parent": {"database_id": config.BUG_DB_ID},
        "icon": {"type": "emoji", "emoji": "🐛"},
        "properties": props,
        "children": children[:100],
    })
```

Trong `create_feature`: đổi tham số `image_urls: Optional[list[str]] = None,` thành `images: Optional[list[Image]] = None,` và thay khối:

```python
    if image_urls:
        children += _text_block("heading_2", "Tham khảo")
        for url in image_urls:
            children.append({
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": url}},
            })
```

bằng:

```python
    image_blocks = await _image_blocks(images)
    if image_blocks:
        children += _text_block("heading_2", "Tham khảo") + image_blocks
```

- [ ] **Step 7: `set_github_issue`, `parse_bug_blocks`, `read_bug_body`**

Dưới `update_bug_status` thêm:

```python
async def set_github_issue(page_id: str, url: str) -> dict:
    prop = config.BUG_PROPS["github_issue"]
    return await _request("PATCH", f"/pages/{page_id}", json={
        "properties": {prop: {"url": url}}
    })
```

Ngay trên `# ---------------------------------------------------------------- format` thêm:

```python
# ---------------------------------------------------------------- đọc body bug

_BODY_SECTIONS = {"Mô tả": "desc", "Bước tái hiện": "steps"}


def _rich_plain(rich: list[dict]) -> str:
    return "".join(x.get("plain_text", "") for x in rich or [])


def parse_bug_blocks(blocks: list[dict]) -> tuple[str, str, list[tuple[str, str]]]:
    """Block con của page bug → (mô tả, bước tái hiện, [(block_id, url ảnh)])."""
    section = None
    text: dict[str, list[str]] = {"desc": [], "steps": []}
    images: list[tuple[str, str]] = []
    for b in blocks:
        t = b.get("type")
        if t in ("heading_1", "heading_2", "heading_3"):
            section = _BODY_SECTIONS.get(_rich_plain(b[t].get("rich_text")).strip())
        elif t == "paragraph" and section:
            text[section].append(_rich_plain(b["paragraph"].get("rich_text")))
        elif t == "image":
            img = b["image"]
            kind = img.get("type")
            url = (img.get(kind) or {}).get("url") if kind in ("file", "external") else None
            if url:
                images.append((b["id"], url))
    return "\n".join(text["desc"]).strip(), "\n".join(text["steps"]).strip(), images


async def _list_children(page_id: str) -> list[dict]:
    blocks: list[dict] = []
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        data = await _request("GET", f"/blocks/{page_id}/children", params=params)
        blocks.extend(data.get("results", []))
        if not data.get("has_more"):
            return blocks
        cursor = data.get("next_cursor")


async def read_bug_body(page_id: str) -> tuple[str, str, list[tuple[str, str]]]:
    return parse_bug_blocks(await _list_children(page_id))
```

- [ ] **Step 8: Chạy test, xác nhận PASS**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS. (`bot.py` vẫn gọi `image_urls=` — sẽ sửa ở Task 6; test hiện có không gọi các hàm đó.)

- [ ] **Step 9: Kiểm chứng File Upload API với Notion thật** (spec yêu cầu xác nhận `Notion-Version: 2022-06-28`)

Điều kiện: người dùng đã thêm 4 cột vào Bug Tracker trên Notion: `Nhân vật` (Text), `Cấp` (Number), `Bản đồ` (Text), `GitHub Issue` (URL). Chưa thêm thì dừng và nhờ người dùng thêm.

Tạo file tạm `smoke_upload.py` trong scratchpad (không commit) và chạy từ thư mục repo:

```python
import asyncio, base64, sys
sys.path.insert(0, ".")
import notion_client as nc

# PNG 1x1 hợp lệ
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

async def main():
    page = await nc.create_bug(
        title="[TEST] smoke upload — xoá được", description="test",
        character="Test", level=1, map_name="Test", images=[(PNG, "t.png", "image/png")],
    )
    desc, steps, images = await nc.read_bug_body(page["id"])
    print("images:", images)
    await nc._request("PATCH", f"/pages/{page['id']}", json={"archived": True})
    assert images, "Ảnh không gắn được vào page"

asyncio.run(main())
```

Run: `.venv/Scripts/python.exe <scratchpad>/smoke_upload.py`
Expected: in ra `images: [('<block id>', 'https://prod-files-secure...')]`, page test được archive.
Nếu Notion trả 400 liên quan version ở `/file_uploads`: thêm hằng `NOTION_FILE_VERSION = "2026-03-11"` vào `config.py` và trong `_request`, khi `path.startswith("/file_uploads")` thì `headers["Notion-Version"] = config.NOTION_FILE_VERSION`; chạy lại. Nếu lỗi là thiếu property → kiểm tra lại tên 4 cột.

- [ ] **Step 10: Commit**

```bash
git add config.py notion_client.py tests/test_notion_bug.py
git commit -m "Notion: cột Nhân vật/Cấp/Bản đồ/GitHub Issue, upload ảnh bằng File Upload API, đọc body bug

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Issue pipeline

**Files:**
- Create: `issue_pipeline.py`
- Create: `tests/notion_fixtures.py`
- Test: `tests/test_issue_pipeline.py`

**Interfaces:**
- Consumes: `issue_models.*` (Task 1), `llm_client.draft_issue`, `LLMError` (Task 2), `github_client.create_issue`, `put_asset`, `GitHubError`, `config.GITHUB_ENABLED`, `config.GITHUB_LABELS` (Task 3), `notion_client.get_page`, `read_bug_body`, `set_github_issue`, `log_history`, `get_prop`, `get_title`, `get_short_id`, `page_url`, `config.BUG_PROPS` (Task 4)
- Produces:
  - `issue_pipeline.MAX_CLARIFY_ROUNDS = 2`
  - `issue_pipeline.PipelineError(Exception)` — message thân thiện
  - `issue_pipeline.enabled() -> bool`
  - `issue_pipeline.bug_from_page(page: dict, description: str, steps: str, images: list[tuple[str, str]]) -> BugInput`
  - `async issue_pipeline.load_bug(page_id: str) -> BugInput`
  - `async issue_pipeline.draft(bug: BugInput, qa: list[tuple[str, str]], final: bool) -> Draft` — `final=True` luôn trả `ready`
  - `async issue_pipeline.publish(bug: BugInput, fields: IssueFields) -> str` — URL issue (đã có thì trả luôn)
  - `tests/notion_fixtures.bug_page(page_id="page-1", **overrides) -> dict`, `tests/notion_fixtures.url_prop(url) -> dict` — dùng lại ở Task 9

- [ ] **Step 1: Viết fixture page Notion**

`tests/notion_fixtures.py`:

```python
"""Page Notion giả cho test (đúng hình dạng API trả về)."""
import config

P = config.BUG_PROPS


def _rt(text):
    return [{"plain_text": text, "type": "text", "text": {"content": text}}]


def bug_page(page_id: str = "page-1", **overrides) -> dict:
    """overrides: key trong BUG_PROPS → property dict; giá trị None → xoá property (page cũ)."""
    props = {
        P["title"]: {"type": "title", "title": _rt("Rớt mạng")},
        P["id"]: {"type": "unique_id", "unique_id": {"prefix": "BUG", "number": 12}},
        P["status"]: {"type": "select", "select": {"name": "Mới báo cáo"}},
        P["severity"]: {"type": "select", "select": {"name": "Cao"}},
        P["version_found"]: {"type": "select", "select": {"name": "v1.2"}},
        P["module"]: {"type": "multi_select", "multi_select": [{"name": "Server"}]},
        P["reporter"]: {"type": "rich_text", "rich_text": _rt("@dee")},
        P["character"]: {"type": "rich_text", "rich_text": _rt("Thiếu Lâm")},
        P["level"]: {"type": "number", "number": 90},
        P["map"]: {"type": "rich_text", "rich_text": _rt("Tương Dương")},
        P["github_issue"]: {"type": "url", "url": None},
    }
    for key, value in overrides.items():
        if value is None:
            props.pop(P[key], None)
        else:
            props[P[key]] = value
    return {"id": page_id, "properties": props}


def url_prop(url):
    return {"type": "url", "url": url}
```

- [ ] **Step 2: Viết test pipeline**

`tests/test_issue_pipeline.py`:

```python
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
```

- [ ] **Step 3: Chạy test, xác nhận FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_issue_pipeline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'issue_pipeline'`

- [ ] **Step 4: Viết `issue_pipeline.py`**

```python
"""Điều phối: bug trên Notion → LLM → ảnh → GitHub issue → ghi ngược Notion.

Không biết gì về Telegram — bot.py gọi các hàm ở đây và tự lo phần nhắn tin.
Mọi lỗi được gói thành PipelineError với message hiện được cho user.
"""
import logging
from typing import Optional
from urllib.parse import urlparse

import httpx

import config
import github_client as gh
import llm_client
import notion_client as nc
from issue_models import BugInput, Draft, IssueFields
from issue_template import render_body, render_title

log = logging.getLogger(__name__)

MAX_CLARIFY_ROUNDS = 2
_TRANSPORT = None  # test gắn httpx.MockTransport

_EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}


class PipelineError(Exception):
    """Không tạo được issue. Message hiện được cho user."""


def enabled() -> bool:
    return config.GITHUB_ENABLED


def bug_from_page(
    page: dict, description: str, steps: str, images: list[tuple[str, str]]
) -> BugInput:
    p = config.BUG_PROPS
    level_raw = nc.get_prop(page, p["level"])
    level: Optional[int] = int(float(level_raw)) if level_raw else None
    return BugInput(
        page_id=page["id"],
        bug_id=nc.get_short_id(page, p["id"]),
        notion_url=nc.page_url(page["id"]),
        title=nc.get_title(page, p["title"]),
        description=description,
        steps=steps,
        severity=nc.get_prop(page, p["severity"]),
        version=nc.get_prop(page, p["version_found"]),
        modules=nc.get_prop(page, p["module"]),
        character=nc.get_prop(page, p["character"]),
        level=level,
        map_name=nc.get_prop(page, p["map"]),
        images=images,
        github_issue=nc.get_prop(page, p["github_issue"]),
    )


async def load_bug(page_id: str) -> BugInput:
    try:
        page = await nc.get_page(page_id)
        description, steps, images = await nc.read_bug_body(page_id)
    except Exception as exc:
        log.exception("Đọc bug %s từ Notion thất bại", page_id)
        raise PipelineError("không đọc được bug từ Notion") from exc
    return bug_from_page(page, description, steps, images)


async def draft(bug: BugInput, qa: list[tuple[str, str]], final: bool) -> Draft:
    try:
        d = await llm_client.draft_issue(bug, qa, final)
    except llm_client.LLMError as exc:
        raise PipelineError(str(exc)) from exc
    if final and d.status == "need_info":
        d = Draft(status="ready", questions=[], issue=d.issue)
    return d


def _ext(url: str, content_type: str) -> str:
    ext = _EXT_BY_TYPE.get((content_type or "").split(";")[0].strip().lower())
    if ext:
        return ext
    path = urlparse(url).path.lower()
    for candidate in _EXT_BY_TYPE.values():
        if path.endswith(candidate):
            return candidate
    return ".jpg"


async def _download(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, transport=_TRANSPORT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "")


async def _upload_images(bug: BugInput) -> tuple[list[str], int]:
    links: list[str] = []
    failed = 0
    for block_id, url in bug.images:
        try:
            data, content_type = await _download(url)
            path = f"bug-assets/{bug.bug_id}/{block_id.replace('-', '')}{_ext(url, content_type)}"
            links.append(await gh.put_asset(path, data, f"{bug.bug_id}: ảnh bug"))
        except Exception:
            log.warning("Không chuyển được ảnh %s của %s sang GitHub", block_id, bug.bug_id, exc_info=True)
            failed += 1
    return links, failed


async def publish(bug: BugInput, fields: IssueFields) -> str:
    """Tạo issue (nếu page chưa có) rồi ghi URL + lịch sử vào Notion. Trả URL issue."""
    try:
        page = await nc.get_page(bug.page_id)
    except Exception as exc:
        raise PipelineError("không đọc được bug từ Notion") from exc
    existing = nc.get_prop(page, config.BUG_PROPS["github_issue"])
    if existing:
        return existing

    links, failed = await _upload_images(bug)
    try:
        number, url = await gh.create_issue(
            render_title(bug, fields),
            render_body(bug, fields, links, failed),
            config.GITHUB_LABELS,
        )
    except gh.GitHubError as exc:
        raise PipelineError(str(exc)) from exc

    try:
        await nc.set_github_issue(bug.page_id, url)
        await nc.log_history(bug.page_id, f"Tạo GitHub issue #{number}")
    except Exception:
        log.exception("Đã tạo issue %s nhưng ghi ngược Notion thất bại", url)
    return url
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS

- [ ] **Step 6: Commit**

```bash
git add issue_pipeline.py tests/notion_fixtures.py tests/test_issue_pipeline.py
git commit -m "Thêm issue_pipeline: Notion → LLM → ảnh → GitHub issue → ghi ngược Notion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Bot — ảnh tải về bytes thay cho link Telegram

**Files:**
- Modify: `bot.py` (`_photo_url` → `_photo_file`; `quick_bug`, `quick_feature`, `bug_image`, `feat_image`)
- Test: `tests/test_bot_github.py`

**Interfaces:**
- Consumes: `notion_client.Image`, `create_bug(..., images=...)`, `create_feature(..., images=...)` (Task 4)
- Produces:
  - `bot.MAX_IMAGE_BYTES = 5 * 1024 * 1024`
  - `bot._too_big(size: Optional[int]) -> bool`
  - `async bot._photo_file(update, context) -> tuple[Optional[nc.Image], bool]` — `(ảnh, quá_lớn)`
  - `bot.TOO_BIG_NOTE: str`

- [ ] **Step 1: Viết test**

`tests/test_bot_github.py`:

```python
"""Test các hàm thuần trong bot.py cho luồng GitHub issue (không gọi mạng)."""
import bot


def test_too_big():
    assert bot._too_big(None) is False
    assert bot._too_big(0) is False
    assert bot._too_big(bot.MAX_IMAGE_BYTES) is False
    assert bot._too_big(bot.MAX_IMAGE_BYTES + 1) is True
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bot_github.py -q`
Expected: FAIL — `AttributeError: module 'bot' has no attribute '_too_big'`

- [ ] **Step 3: Thay `_photo_url` bằng `_photo_file`**

Thay toàn bộ hàm `_photo_url` trong `bot.py` bằng:

```python
# Workspace Notion free giới hạn 5 MB/file
MAX_IMAGE_BYTES = 5 * 1024 * 1024
TOO_BIG_NOTE = "\n\n<i>⚠️ Ảnh lớn hơn 5 MB nên không đính kèm.</i>"


def _too_big(size: Optional[int]) -> bool:
    return bool(size) and size > MAX_IMAGE_BYTES


async def _photo_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> tuple[Optional[nc.Image], bool]:
    """Tải ảnh từ chính tin nhắn, hoặc từ tin nhắn được reply. Trả (ảnh, quá_lớn).

    Tải về bytes để upload lên Notion — không dùng File.file_path vì URL đó chứa token bot.
    """
    for msg in (update.message, update.message.reply_to_message):
        if not msg:
            continue
        if msg.photo:
            ph = msg.photo[-1]
            file_id, size = ph.file_id, ph.file_size
            filename, content_type = f"{ph.file_unique_id}.jpg", "image/jpeg"
        elif msg.document and (msg.document.mime_type or "").startswith("image/"):
            doc = msg.document
            file_id, size = doc.file_id, doc.file_size
            filename, content_type = doc.file_name or f"{doc.file_unique_id}.jpg", doc.mime_type
        else:
            continue
        if _too_big(size):
            return None, True
        f = await context.bot.get_file(file_id)
        data = bytes(await f.download_as_bytearray())
        if _too_big(len(data)):
            return None, True
        return (data, filename, content_type), False
    return None, False
```

- [ ] **Step 4: Sửa 4 chỗ gọi**

`quick_bug` — thay:

```python
    title, desc = _split_args(raw)
    urls = []
    url = await _photo_url(update, context)
    if url:
        urls.append(url)
```

bằng:

```python
    title, desc = _split_args(raw)
    photo, too_big = await _photo_file(update, context)
    images = [photo] if photo else []
```

rồi trong lời gọi `nc.create_bug(...)` của `quick_bug` đổi `image_urls=urls,` thành `images=images,`, và thay đoạn trả lời:

```python
    text, kb = _bug_card(page)
    hint = "" if urls else "\n\n<i>Bấm nút bên dưới để bổ sung thông tin.</i>"
    await update.message.reply_text(
        f"✅ Đã ghi nhận\n\n{text}{hint}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
```

bằng:

```python
    text, kb = _bug_card(page)
    hint = "" if images else "\n\n<i>Bấm nút bên dưới để bổ sung thông tin.</i>"
    if too_big:
        hint += TOO_BIG_NOTE
    await update.message.reply_text(
        f"✅ Đã ghi nhận\n\n{text}{hint}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
```

`quick_feature` — thay khối `urls = [] / url = await _photo_url(update, context) / if url: urls.append(url)` bằng:

```python
    photo, too_big = await _photo_file(update, context)
    images = [photo] if photo else []
```

đổi `image_urls=urls,` thành `images=images,`, và đổi đoạn trả lời cuối hàm thành:

```python
    await update.message.reply_text(
        f"✅ Đã ghi nhận\n\n{text}" + (TOO_BIG_NOTE if too_big else ""),
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
```

`bug_image` — thay khối `urls = [] / url = await _photo_url(update, context) / if url: urls.append(url)` ở đầu hàm bằng:

```python
    photo, too_big = await _photo_file(update, context)
    images = [photo] if photo else []
```

đổi `image_urls=urls,` thành `images=images,`, và đổi dòng `confirm = f"✅ Đã ghi nhận\n\n{text}"` thành:

```python
    confirm = f"✅ Đã ghi nhận\n\n{text}" + (TOO_BIG_NOTE if too_big else "")
```

`feat_image` — cùng ba thay đổi như `bug_image` (khối tải ảnh ở đầu hàm, `images=images,`, dòng `confirm`).

- [ ] **Step 5: Kiểm tra không còn dấu vết cũ**

Run: `grep -n "_photo_url\|image_urls\|file_path" bot.py notion_client.py`
Expected: không có kết quả

- [ ] **Step 6: Chạy test, xác nhận PASS**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS

- [ ] **Step 7: Commit**

```bash
git add bot.py tests/test_bot_github.py
git commit -m "Ảnh bug/feature tải về rồi upload lên Notion, không lưu link Telegram chứa token

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Bot — thêm bước Nhân vật / Cấp / Bản đồ

**Files:**
- Modify: `bot.py` (hằng state, `bug_steps`, 3 handler mới, `bug_image`, `main`)
- Test: `tests/test_bot_github.py`

**Interfaces:**
- Consumes: `notion_client.create_bug(character=, level=, map_name=)` (Task 4)
- Produces:
  - State mới: `BUG_CHAR`, `BUG_LEVEL`, `BUG_MAP`, `BUG_CLARIFY` (Task 8 dùng `BUG_CLARIFY`)
  - `bot._parse_level(text: str) -> Optional[int]`
  - `bot.bug_char`, `bot.bug_level`, `bot.bug_map` (handler)
  - `user_data` keys: `"character"`, `"level"`, `"map"`

- [ ] **Step 1: Thêm test**

Nối vào `tests/test_bot_github.py`:

```python


def test_parse_level():
    assert bot._parse_level("90") == 90
    assert bot._parse_level(" cấp 90 ") == 90
    assert bot._parse_level("Cấp90") == 90
    assert bot._parse_level("Lv.120") == 120
    assert bot._parse_level("lv 5") == 5
    assert bot._parse_level("level 7") == 7


def test_parse_level_rejects_garbage():
    for text in ("", "abc", "0", "90 thiếu lâm", "-5", "12345", "1000"):
        assert bot._parse_level(text) is None, text
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bot_github.py -q`
Expected: FAIL — `AttributeError: module 'bot' has no attribute '_parse_level'`

- [ ] **Step 3: Đổi hằng state**

Thay:

```python
(
    BUG_TITLE, BUG_DESC, BUG_STEPS, BUG_SEVERITY,
    BUG_VERSION, BUG_MODULE, BUG_IMAGE,
) = range(7)
```

bằng:

```python
(
    BUG_TITLE, BUG_DESC, BUG_STEPS, BUG_CHAR, BUG_LEVEL, BUG_MAP,
    BUG_SEVERITY, BUG_VERSION, BUG_MODULE, BUG_IMAGE, BUG_CLARIFY,
) = range(11)
```

- [ ] **Step 4: `_parse_level`** — thêm ngay dưới `_normalize_version`:

```python
_LEVEL_RE = re.compile(r"^(?:cấp|cap|lv\.?|level)?\s*(\d{1,4})$", re.IGNORECASE)


def _parse_level(text: str) -> Optional[int]:
    """'90', 'cấp 90', 'Lv.120' → số. Không phải số / bằng 0 / từ 1000 trở lên → None."""
    m = _LEVEL_RE.match((text or "").strip())
    if not m:
        return None
    level = int(m.group(1))
    return level if 0 < level < 1000 else None
```

- [ ] **Step 5: Handler cho 3 bước mới**

Thay `bug_steps` bằng:

```python
async def bug_steps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["steps"] = "" if text == SKIP else text
    await update.message.reply_text(
        "Nhân vật gặp lỗi (môn phái / tên nhân vật)?", reply_markup=_kb([], add_skip=True)
    )
    return BUG_CHAR


async def bug_char(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["character"] = "" if text == SKIP else text
    await update.message.reply_text("Cấp nhân vật?", reply_markup=_kb([], add_skip=True))
    return BUG_LEVEL


async def bug_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == SKIP:
        context.user_data["level"] = None
    else:
        level = _parse_level(text)
        if level is None:
            await update.message.reply_text(
                "Cấp là số, vd 90. Hoặc bấm Bỏ qua.", reply_markup=_kb([], add_skip=True)
            )
            return BUG_LEVEL
        context.user_data["level"] = level
    await update.message.reply_text("Gặp lỗi ở bản đồ nào?", reply_markup=_kb([], add_skip=True))
    return BUG_MAP


async def bug_map(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["map"] = "" if text == SKIP else text
    await update.message.reply_text("Mức độ nghiêm trọng?", reply_markup=_kb(config.SEVERITIES))
    return BUG_SEVERITY
```

- [ ] **Step 6: Truyền 3 trường vào `create_bug` trong `bug_image`**

Trong lời gọi `nc.create_bug(...)` của `bug_image`, thêm sau dòng `modules=d.get("modules"),`:

```python
            character=d.get("character", ""),
            level=d.get("level"),
            map_name=d.get("map", ""),
```

- [ ] **Step 7: Đăng ký state trong `main()`**

Trong `states={...}` của ConversationHandler, ngay sau dòng `BUG_STEPS: [...]` thêm:

```python
            BUG_CHAR: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, bug_char)],
            BUG_LEVEL: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, bug_level)],
            BUG_MAP: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, bug_map)],
```

- [ ] **Step 8: Chạy test, xác nhận PASS**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS

- [ ] **Step 9: Commit**

```bash
git add bot.py tests/test_bot_github.py
git commit -m "Luồng /bug hỏi thêm Nhân vật, Cấp, Bản đồ và lưu lên Notion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Bot — luồng GitHub trong chat riêng (hỏi lại, /boqua, timeout, deep-link clarify)

**Files:**
- Modify: `bot.py` (import, section GitHub mới, `bug_image`, `start_or_deeplink`, tách `_build_conversation()` khỏi `main()`)
- Test: `tests/test_bot_github.py`

**Interfaces:**
- Consumes: `issue_pipeline.enabled`, `load_bug`, `draft`, `publish`, `PipelineError`, `MAX_CLARIFY_ROUNDS` (Task 5); `BUG_CHAR`, `BUG_LEVEL`, `BUG_MAP`, `BUG_CLARIFY`, `bug_char`, `bug_level`, `bug_map` (Task 7); `nc.find_by_short_id`, `nc.log_history`
- Produces (Task 9 dùng):
  - `bot._issue_number(url: str) -> str`
  - `bot._issue_kb(url: str) -> InlineKeyboardMarkup`
  - `bot._fail_text(bug_id: str, exc: Exception) -> str`
  - `bot._clarify_payload(bug_id: str) -> str` — `"BUG-12"` → `"clarify_12"`
  - `bot._clarify_url(bug_id: str) -> str`
  - `bot._build_conversation() -> ConversationHandler`
  - `bot.bug_clarify`, `bot.bug_clarify_skip`, `bot.on_conv_timeout`, `bot.on_busy` (handler)
  - `user_data` keys: `gh_bug`, `gh_draft`, `gh_questions`, `gh_rounds`, `gh_qa`

- [ ] **Step 1: Thêm test**

Nối vào `tests/test_bot_github.py`:

```python


def test_issue_number():
    assert bot._issue_number("https://github.com/t/g/issues/34") == "34"
    assert bot._issue_number("https://github.com/t/g/issues/34/") == "34"


def test_clarify_payload_and_url(monkeypatch):
    monkeypatch.setattr(bot, "BOT_USERNAME", "vltk_bot")
    assert bot._clarify_payload("BUG-12") == "clarify_12"
    assert bot._clarify_url("BUG-12") == "https://t.me/vltk_bot?start=clarify_12"


def test_fail_text_escapes_and_mentions_issue_command():
    text = bot._fail_text("BUG-7", Exception("LLM trả lỗi <500>"))
    assert "&lt;500&gt;" in text
    assert "/issue BUG-7" in text


def test_conversation_has_waiting_state_and_nonblocking_slow_handlers():
    from telegram.ext import ConversationHandler

    conv = bot._build_conversation()
    assert ConversationHandler.WAITING in conv.states
    assert ConversationHandler.TIMEOUT in conv.states
    assert bot.BUG_CLARIFY in conv.states
    slow = {bot.bug_image, bot.bug_clarify, bot.bug_clarify_skip, bot.start_or_deeplink}
    handlers = [h for hs in conv.states.values() for h in hs] + list(conv.entry_points)
    found = {h.callback for h in handlers if h.callback in slow}
    assert found == slow
    for h in handlers:
        if h.callback in slow:
            assert h.block is False, h.callback.__name__
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bot_github.py -q`
Expected: FAIL — `AttributeError: module 'bot' has no attribute '_issue_number'`

- [ ] **Step 3: Import**

Trong khối `from telegram.ext import (...)` thêm `TypeHandler,` ngay sau `MessageHandler,`. Dưới `import notion_client as nc` thêm:

```python
import issue_pipeline as ip
```

- [ ] **Step 4: Section GitHub**

Thêm section mới ngay trên dòng `# ================================================================ hội thoại đầy đủ (chat riêng)`:

```python
# ================================================================ GitHub issue (LLM)

_GH_KEYS = ("gh_bug", "gh_draft", "gh_questions", "gh_rounds", "gh_qa")


def _issue_number(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _issue_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🐙 Mở GitHub issue", url=url)]])


def _fail_text(bug_id: str, exc: Exception) -> str:
    return (
        f"⚠️ Chưa tạo được GitHub issue: {html.escape(str(exc))}.\n"
        f"Bug đã lưu Notion — admin chạy <code>/issue {html.escape(bug_id)}</code>."
    )


def _clarify_payload(bug_id: str) -> str:
    return f"clarify_{bug_id.split('-')[-1]}"


def _clarify_url(bug_id: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={_clarify_payload(bug_id)}"


def _clear_gh(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in _GH_KEYS:
        context.user_data.pop(key, None)


async def _gh_publish(message, context: ContextTypes.DEFAULT_TYPE, bug, fields) -> int:
    try:
        url = await ip.publish(bug, fields)
    except ip.PipelineError as exc:
        await message.reply_text(_fail_text(bug.bug_id, exc), parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(
            f"🐙 Đã tạo GitHub issue #{_issue_number(url)} cho {bug.bug_id}.",
            reply_markup=_issue_kb(url),
        )
    _clear_gh(context)
    return ConversationHandler.END


async def _gh_step(message, context: ContextTypes.DEFAULT_TYPE, bug, final: bool) -> int:
    """Một vòng LLM: đủ rõ → tạo issue; chưa rõ → gửi câu hỏi, chờ ở BUG_CLARIFY."""
    ud = context.user_data
    await message.chat.send_action("typing")
    try:
        d = await ip.draft(bug, ud.get("gh_qa", []), final)
    except ip.PipelineError as exc:
        await message.reply_text(_fail_text(bug.bug_id, exc), parse_mode=ParseMode.HTML)
        _clear_gh(context)
        return ConversationHandler.END

    if d.status == "ready":
        return await _gh_publish(message, context, bug, d.issue)

    ud["gh_bug"] = bug
    ud["gh_draft"] = d
    ud["gh_questions"] = d.questions
    ud["gh_rounds"] = ud.get("gh_rounds", 0) + 1
    questions = "\n".join(f"{i}. {html.escape(q)}" for i, q in enumerate(d.questions, 1))
    await message.reply_text(
        f"🤔 Để tạo GitHub issue cho <b>{bug.bug_id}</b>, cần làm rõ thêm:\n\n{questions}\n\n"
        "<i>Trả lời trong 1 tin nhắn, hoặc /boqua để tạo issue với thông tin hiện có.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
    return BUG_CLARIFY


async def _gh_begin(message, context: ContextTypes.DEFAULT_TYPE, page_id: str) -> int:
    """Bắt đầu tạo issue cho 1 bug (vừa lưu, hoặc mở từ nút Bổ sung)."""
    _clear_gh(context)
    await message.reply_text("⏳ Đang soạn GitHub issue…")
    try:
        bug = await ip.load_bug(page_id)
    except ip.PipelineError as exc:
        await message.reply_text(
            f"⚠️ Chưa tạo được GitHub issue: {html.escape(str(exc))}.", parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END
    if bug.github_issue:
        await message.reply_text(
            f"{bug.bug_id} đã có GitHub issue.", reply_markup=_issue_kb(bug.github_issue)
        )
        return ConversationHandler.END
    return await _gh_step(message, context, bug, final=False)


async def bug_clarify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ud = context.user_data
    bug = ud.get("gh_bug")
    if not bug:
        return ConversationHandler.END
    answer = update.message.text.strip()
    questions = "\n".join(ud.get("gh_questions", []))
    ud.setdefault("gh_qa", []).append((questions, answer))
    try:
        await nc.log_history(bug.page_id, f"Bổ sung cho GitHub: {questions} → {answer}")
    except Exception:
        log.exception("Ghi lịch sử bổ sung GitHub thất bại")
    final = ud.get("gh_rounds", 0) >= ip.MAX_CLARIFY_ROUNDS
    return await _gh_step(update.message, context, bug, final)


async def bug_clarify_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/boqua — tạo issue luôn từ bản nháp hiện có."""
    ud = context.user_data
    bug, d = ud.get("gh_bug"), ud.get("gh_draft")
    if not bug or not d:
        return ConversationHandler.END
    return await _gh_publish(update.message, context, bug, d.issue)


async def on_conv_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hết 10 phút: nếu đang chờ bổ sung cho GitHub thì tạo issue từ bản nháp, không để mất."""
    ud = context.user_data
    bug, d = ud.get("gh_bug"), ud.get("gh_draft")
    if bug and d:
        try:
            url = await ip.publish(bug, d.issue)
            text = (f"⏰ Hết thời gian chờ — đã tạo GitHub issue #{_issue_number(url)} "
                    f"cho {bug.bug_id} với thông tin hiện có.")
            kb = _issue_kb(url)
        except ip.PipelineError as exc:
            text, kb = _fail_text(bug.bug_id, exc), None
        try:
            await context.bot.send_message(
                update.effective_chat.id, text, parse_mode=ParseMode.HTML, reply_markup=kb
            )
        except Exception:
            log.warning("Không nhắn được kết quả timeout cho %s", update.effective_chat.id)
    ud.clear()


async def on_busy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tin nhắn đến trong lúc bot còn xử lý bước trước (state WAITING)."""
    await update.message.reply_text("⏳ Bot đang xử lý tin trước, chờ chút rồi gửi lại nhé.")


async def _clarify_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, num: str) -> int:
    """Deep-link clarify_<số> từ nút "Bổ sung cho GitHub issue" trong group."""
    if not ip.enabled():
        await update.message.reply_text("GitHub issue chưa được cấu hình.")
        return ConversationHandler.END
    bug_id = f"BUG-{num}"
    page = await nc.find_by_short_id(config.BUG_DB_ID, config.BUG_PROPS["id"], bug_id)
    if not page:
        await update.message.reply_text(f"Không tìm thấy {bug_id}.")
        return ConversationHandler.END
    context.user_data.clear()
    return await _gh_begin(update.message, context, page["id"])
```

- [ ] **Step 5: Nối vào cuối `bug_image`**

Thay **hai dòng cuối** của `bug_image` (nhánh `except` bên trên giữ nguyên):

```python
    context.user_data.clear()
    return ConversationHandler.END
```

bằng:

```python
    context.user_data.clear()
    if ip.enabled():
        return await _gh_begin(update.message, context, page["id"])
    return ConversationHandler.END
```

- [ ] **Step 6: Deep-link trong `start_or_deeplink`**

Ngay sau dòng `action, _, origin = payload.partition("_")` thêm:

```python
    if action == "clarify" and origin.isdigit():
        return await _clarify_entry(update, context, origin)
```

- [ ] **Step 7: Tách `_build_conversation()` và đăng ký handler**

Thêm hàm ngay trên `def main()`:

```python
def _build_conversation() -> ConversationHandler:
    private = filters.ChatType.PRIVATE
    text = private & filters.TEXT & ~filters.COMMAND
    image = private & (filters.PHOTO | filters.Document.IMAGE | filters.TEXT) & ~filters.COMMAND

    # Hội thoại đầy đủ — chỉ chạy trong chat riêng để không nuốt tin nhắn group.
    # Handler chậm (gọi LLM/GitHub) đặt block=False để không chặn user khác; tin nhắn đến
    # trong lúc chờ rơi vào state WAITING thay vì bị hiểu là câu trả lời của bước cũ.
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_or_deeplink, filters=private, block=False),
            CommandHandler("bug", bug_start, filters=private),
            CommandHandler("feature", feat_start, filters=private),
        ],
        states={
            BUG_TITLE: [MessageHandler(text, bug_title)],
            BUG_DESC: [MessageHandler(text, bug_desc)],
            BUG_STEPS: [MessageHandler(text, bug_steps)],
            BUG_CHAR: [MessageHandler(text, bug_char)],
            BUG_LEVEL: [MessageHandler(text, bug_level)],
            BUG_MAP: [MessageHandler(text, bug_map)],
            BUG_SEVERITY: [MessageHandler(text, bug_severity)],
            BUG_VERSION: [MessageHandler(text, bug_version)],
            BUG_MODULE: [MessageHandler(text, bug_module)],
            BUG_IMAGE: [MessageHandler(image, bug_image, block=False)],
            BUG_CLARIFY: [
                MessageHandler(text, bug_clarify, block=False),
                CommandHandler("boqua", bug_clarify_skip, block=False),
            ],
            FEAT_TITLE: [MessageHandler(text, feat_title)],
            FEAT_DESC: [MessageHandler(text, feat_desc)],
            FEAT_IMPACT: [MessageHandler(text, feat_impact)],
            FEAT_EFFORT: [MessageHandler(text, feat_effort)],
            FEAT_IMAGE: [MessageHandler(image, feat_image)],
            ConversationHandler.WAITING: [MessageHandler(private & ~filters.COMMAND, on_busy)],
            ConversationHandler.TIMEOUT: [TypeHandler(Update, on_conv_timeout)],
        },
        fallbacks=[
            CommandHandler("huy", cmd_cancel),
            CommandHandler("cancel", cmd_cancel),
        ],
        conversation_timeout=600,
    )
```

Trong `main()`, xoá khối từ dòng `private = filters.ChatType.PRIVATE` đến hết `app.add_handler(conv)` (gồm comment "Hội thoại đầy đủ…" và toàn bộ `conv = ConversationHandler(...)`) và thay bằng:

```python
    app.add_handler(_build_conversation())
```

Sau đó chạy `grep -n "private" bot.py` — trong `main()` không được còn chỗ nào dùng biến `private`; nếu còn thì giữ lại dòng `private = filters.ChatType.PRIVATE` trong `main()`.

- [ ] **Step 8: Chạy test, xác nhận PASS**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS. PTB có thể in `PTBUserWarning` về cấu hình ConversationHandler — không phải lỗi.

- [ ] **Step 9: Kiểm tra bot dựng được hội thoại**

Run: `.venv/Scripts/python.exe -c "import bot; bot._build_conversation(); print('ok')"`
Expected: in `ok`, không exception.

- [ ] **Step 10: Commit**

```bash
git add bot.py tests/test_bot_github.py
git commit -m "Sau khi lưu bug: LLM soạn GitHub issue, hỏi lại khi mơ hồ (/boqua, timeout, deep-link clarify)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Bot — báo nhanh trong group, thẻ bug có nút GitHub, lệnh /issue

**Files:**
- Modify: `bot.py` (`_bug_card`, `on_field_click`, `quick_bug`, lệnh mới `cmd_issue`, help, BotCommand, `main`)
- Test: `tests/test_bot_github.py`

**Interfaces:**
- Consumes: `_issue_number`, `_issue_kb`, `_fail_text`, `_clarify_url` (Task 8); `ip.*` (Task 5); `tests/notion_fixtures.bug_page`, `url_prop` (Task 5)
- Produces:
  - `bot._bug_card(page: dict, clarify_url: Optional[str] = None) -> tuple[str, InlineKeyboardMarkup]`
  - `bot._clarify_button_url(markup: Optional[InlineKeyboardMarkup]) -> Optional[str]`
  - `async bot.cmd_issue(update, context) -> None`

- [ ] **Step 1: Thêm test**

Nối vào `tests/test_bot_github.py`:

```python


from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from notion_fixtures import bug_page, url_prop


def _urls(kb):
    return [b.url for row in kb.inline_keyboard for b in row if b.url]


def test_bug_card_buttons():
    issue = "https://github.com/t/g/issues/34"
    clarify = "https://t.me/vltk_bot?start=clarify_12"

    _, kb = bot._bug_card(bug_page())
    assert issue not in _urls(kb) and clarify not in _urls(kb)

    _, kb = bot._bug_card(bug_page(github_issue=url_prop(issue)))
    assert issue in _urls(kb)

    _, kb = bot._bug_card(bug_page(), clarify_url=clarify)
    assert clarify in _urls(kb)

    # Đã có issue thì không hiện nút Bổ sung nữa
    _, kb = bot._bug_card(bug_page(github_issue=url_prop(issue)), clarify_url=clarify)
    assert issue in _urls(kb) and clarify not in _urls(kb)


def test_clarify_button_url_found():
    clarify = "https://t.me/vltk_bot?start=clarify_12"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟠 Cao", callback_data="sv|x|1")],
        [InlineKeyboardButton("✍️ Bổ sung cho GitHub issue", url=clarify)],
    ])
    assert bot._clarify_button_url(markup) == clarify


def test_clarify_button_url_absent():
    assert bot._clarify_button_url(None) is None
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📄 Notion", url="https://notion.so/x")]])
    assert bot._clarify_button_url(markup) is None
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bot_github.py -q`
Expected: FAIL — `TypeError: _bug_card() got an unexpected keyword argument 'clarify_url'` / thiếu `_clarify_button_url`

- [ ] **Step 3: `_bug_card` hiện nút GitHub / Bổ sung**

Đổi dòng khai báo thành:

```python
def _bug_card(page: dict, clarify_url: Optional[str] = None) -> tuple[str, InlineKeyboardMarkup]:
```

Trong thân, thêm sau dòng `reporter = nc.get_prop(page, p["reporter"])`:

```python
    gh_url = nc.get_prop(page, p["github_issue"])
```

và thay hai dòng cuối:

```python
    rows.append([InlineKeyboardButton("📄 Mở trong Notion", url=nc.page_url(page["id"]))])
    return text, InlineKeyboardMarkup(rows)
```

bằng:

```python
    links = [InlineKeyboardButton("📄 Mở trong Notion", url=nc.page_url(page["id"]))]
    if gh_url:
        links.append(InlineKeyboardButton(f"🐙 GitHub #{_issue_number(gh_url)}", url=gh_url))
    rows.append(links)
    if clarify_url and not gh_url:
        rows.append([InlineKeyboardButton("✍️ Bổ sung cho GitHub issue", url=clarify_url)])
    return text, InlineKeyboardMarkup(rows)
```

Thêm ngay dưới `_bug_card`:

```python
def _clarify_button_url(markup: Optional[InlineKeyboardMarkup]) -> Optional[str]:
    """URL nút "Bổ sung cho GitHub issue" đang có trên thẻ, để vẽ lại thẻ không làm mất nó."""
    if not markup:
        return None
    for row in markup.inline_keyboard:
        for button in row:
            if button.url and "?start=clarify_" in button.url:
                return button.url
    return None
```

- [ ] **Step 4: `on_field_click` giữ nút Bổ sung khi vẽ lại thẻ**

Trong `on_field_click`, ngay sau `p = config.BUG_PROPS` thêm:

```python
    clarify = _clarify_button_url(query.message.reply_markup)
```

Trong nhánh `if kind == "mx":`, thay dòng:

```python
        rows.append([InlineKeyboardButton("↩️ Bỏ qua", callback_data=f"mn|{pid}|0")])
```

bằng:

```python
        rows.append([InlineKeyboardButton("↩️ Bỏ qua", callback_data=f"mn|{pid}|0")])
        if clarify:
            rows.append([InlineKeyboardButton("✍️ Bổ sung cho GitHub issue", url=clarify)])
```

Trong nhánh `if kind == "mn":` và ở cuối hàm, đổi cả hai chỗ `text, kb = _bug_card(page)` thành `text, kb = _bug_card(page, clarify_url=clarify)` (giữ nguyên thụt lề từng chỗ).

- [ ] **Step 5: `quick_bug` chạy LLM ở nền rồi sửa thẻ**

Thêm hàm ngay trên `async def quick_feature(`:

```python
async def _quick_github(context: ContextTypes.DEFAULT_TYPE, card, page_id: str, bug_id: str) -> None:
    """Chạy nền sau khi báo nhanh trong group: đủ rõ → tạo issue; chưa rõ → gắn nút Bổ sung."""
    clarify = None
    try:
        bug = await ip.load_bug(page_id)
        d = await ip.draft(bug, [], final=False)
        if d.status == "ready":
            await ip.publish(bug, d.issue)
        else:
            clarify = _clarify_url(bug.bug_id)
        fresh = await nc.get_page(page_id)
    except ip.PipelineError as exc:
        await card.reply_text(_fail_text(bug_id, exc), parse_mode=ParseMode.HTML)
        return
    except Exception:
        log.exception("Luồng GitHub cho %s thất bại", bug_id)
        return
    _, kb = _bug_card(fresh, clarify_url=clarify)
    try:
        await card.edit_reply_markup(reply_markup=kb)
    except Exception:
        log.warning("Không sửa được thẻ bug %s", bug_id)
```

Trong `quick_bug`, thay:

```python
    await update.message.reply_text(
        f"✅ Đã ghi nhận\n\n{text}{hint}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
```

bằng:

```python
    card = await update.message.reply_text(
        f"✅ Đã ghi nhận\n\n{text}{hint}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    if ip.enabled():
        bug_id = nc.get_short_id(page, config.BUG_PROPS["id"])
        context.application.create_task(
            _quick_github(context, card, page["id"], bug_id), update=update
        )
```

- [ ] **Step 6: Lệnh `/issue`**

Thêm ngay trên `async def cmd_me(`:

```python
async def cmd_issue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/issue BUG-12 — tạo GitHub issue ngay, không hỏi lại (admin)."""
    if not await _guard_group(update):
        return
    if not _is_admin(update):
        await update.message.reply_text("Chỉ admin mới tạo được GitHub issue bằng lệnh.")
        return
    bug_id, _ = _parse_bug_args(context.args or [])
    if not bug_id:
        await update.message.reply_text(
            "Cú pháp: <code>/issue BUG-44</code>", parse_mode=ParseMode.HTML
        )
        return
    if not ip.enabled():
        await update.message.reply_text(
            "GitHub issue chưa được cấu hình (thiếu LLM_* / GITHUB_* trong .env)."
        )
        return
    page = await nc.find_by_short_id(config.BUG_DB_ID, config.BUG_PROPS["id"], bug_id)
    if not page:
        await update.message.reply_text(f"Không tìm thấy {bug_id}.")
        return

    await update.message.chat.send_action("typing")
    try:
        bug = await ip.load_bug(page["id"])
        if bug.github_issue:
            await update.message.reply_text(
                f"{bug_id} đã có GitHub issue.", reply_markup=_issue_kb(bug.github_issue)
            )
            return
        d = await ip.draft(bug, [], final=True)
        url = await ip.publish(bug, d.issue)
    except ip.PipelineError as exc:
        await update.message.reply_text(_fail_text(bug_id, exc), parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(
        f"🐙 Đã tạo GitHub issue #{_issue_number(url)} cho {bug_id}.", reply_markup=_issue_kb(url)
    )
```

Trong `main()`, sau dòng `app.add_handler(CommandHandler("reopened", cmd_reopened))` thêm:

```python
    app.add_handler(CommandHandler("issue", cmd_issue, block=False))
```

- [ ] **Step 7: Help + menu lệnh**

`HELP_GROUP`: thay dòng cuối `"/status BUG-12 — chọn trạng thái bất kỳ."` bằng:

```python
    "/status BUG-12 — chọn trạng thái bất kỳ.\n"
    "/issue BUG-12 — tạo GitHub issue cho bug (nếu lần trước lỗi / chưa bổ sung)."
```

`HELP_PRIVATE`: thêm ngay sau dòng `"☑️ /confirmed BUG-44 · 🔁 /reopened BUG-44 lý do\n"`:

```python
    "🐙 /issue BUG-44 — tạo GitHub issue (admin)\n"
```

Trong `_post_init`, thêm vào `group_cmds` ngay sau dòng `BotCommand("reopened", "Mở lại: /reopened BUG-44 lý do"),`:

```python
        BotCommand("issue", "Tạo GitHub issue: /issue BUG-44"),
```

- [ ] **Step 8: Chạy test, xác nhận PASS**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS

- [ ] **Step 9: Commit**

```bash
git add bot.py tests/test_bot_github.py
git commit -m "Báo nhanh trong group cũng tạo GitHub issue (nút Bổ sung), thêm /issue, thẻ bug có nút GitHub

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Tài liệu + smoke test

**Files:**
- Modify: `README.md`, `.env.example`, `env.example.txt`

**Interfaces:**
- Consumes: tên biến môi trường (Task 2, 3), tên cột (Task 4), lệnh `/issue`, `/boqua` (Task 8, 9)
- Produces: không

- [ ] **Step 1: Biến môi trường mẫu**

Nối vào cuối **cả** `.env.example` và `env.example.txt`:

```bash

# ---- GitHub issue tự động (tuỳ chọn) ----
# Thiếu LLM_API_KEY / LLM_MODEL / GITHUB_TOKEN / GITHUB_REPO → tính năng tắt, bot chạy như cũ.

# LLM OpenAI-compatible. DashScope (Qwen) quốc tế:
LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
# DeepSeek: LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=
# Tên model đúng như trong console nhà cung cấp
LLM_MODEL=

# Fine-grained token, chỉ 1 repo, quyền Issues: Read and write + Contents: Read and write
GITHUB_TOKEN=
# owner/repo
GITHUB_REPO=
GITHUB_LABELS=bug
# Branch riêng chứa ảnh bug (tạo 1 lần, xem README)
GITHUB_ASSETS_BRANCH=bug-assets
```

- [ ] **Step 2: README — database Notion**

Trong mục "Notion đã dựng sẵn", dòng mô tả **Bug Tracker**, chèn `Nhân vật, Cấp, Bản đồ, GitHub Issue,` ngay sau `Người xử lý,`.

- [ ] **Step 3: README — mục cài đặt mới**

Thêm mục sau ngay trước `## Cách dùng` (tức là sau mục `### 4. Thêm bot vào group`):

````markdown
### 5. GitHub issue tự động (tuỳ chọn)

Mỗi bug lưu vào Notion được LLM chuyển thành một GitHub issue theo template (Triệu chứng / Cách tái hiện / Môi trường / Log / Miền nghi ngờ) để AI agent đọc. Notion vẫn là nơi người đọc; issue ghi BUG-ID và link Notion, Notion lưu link issue ở cột **GitHub Issue**.

1. **Notion** — thêm 4 cột vào Bug Tracker: `Nhân vật` (Text), `Cấp` (Number), `Bản đồ` (Text), `GitHub Issue` (URL). Tên phải khớp `BUG_PROPS` trong `config.py`.
2. **GitHub token** — github.com → Settings → Developer settings → Fine-grained tokens → chỉ chọn repo nhận issue, quyền **Issues: Read and write** và **Contents: Read and write**.
3. **Branch ảnh** — ảnh bug được commit vào branch riêng để không làm bẩn `main`. Tạo một lần trong clone của repo đó:
   ```bash
   git switch --orphan bug-assets
   git commit --allow-empty -m "bug assets"
   git push -u origin bug-assets
   git switch main
   ```
4. **LLM** — lấy API key ở Alibaba Cloud Model Studio (DashScope) hoặc DeepSeek, điền `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
5. Điền `GITHUB_TOKEN`, `GITHUB_REPO` (`owner/repo`) vào `.env`, restart bot.

Thiếu bất kỳ biến nào ở trên thì tính năng tự tắt, bot chạy như cũ.
````

- [ ] **Step 4: README — cách dùng**

Trong mục "Trong group — khai báo riêng tư", sửa `(tiêu đề → mô tả → bước tái hiện → severity → version → module → ảnh)` thành `(tiêu đề → mô tả → bước tái hiện → nhân vật → cấp → bản đồ → severity → version → module → ảnh)`.

Thêm mục mới ngay trước `### Lệnh chung`:

````markdown
### GitHub issue — khi nào bot hỏi lại

Khai xong, bot báo `✅ Đã ghi nhận` rồi `⏳ Đang soạn GitHub issue…`:

- Nội dung đủ rõ → tạo issue luôn, trả nút **🐙 Mở GitHub issue**.
- Không rõ hiện tượng / không tái hiện được / thông tin mâu thuẫn → bot hỏi tối đa 3 câu. Trả lời trong 1 tin nhắn, hoặc `/boqua` để tạo issue với thông tin hiện có. Tối đa 2 vòng hỏi; bỏ đi quá 10 phút thì bot tự tạo issue từ bản nháp.
- Câu trả lời bổ sung được ghi vào mục **📜 Lịch sử** của page Notion.

Báo nhanh trong group (`/bug Tiêu đề | mô tả`): thẻ bug hiện ngay, vài giây sau bot gắn thêm nút **🐙 GitHub #34**, hoặc **✍️ Bổ sung cho GitHub issue** nếu cần hỏi thêm — bấm nút đó để trả lời trong chat riêng.

Nếu LLM/GitHub lỗi, bug vẫn nằm trong Notion. Admin chạy `/issue BUG-12` để tạo lại (không hỏi thêm).
````

Trong bảng "Lệnh chung" thêm hai dòng ngay sau dòng `/reopened`:

```markdown
| `/issue BUG-12` | Tạo GitHub issue cho bug chưa có (admin) |
| `/boqua` | Đang bị hỏi bổ sung → tạo issue luôn (chat riêng) |
```

- [ ] **Step 5: README — viết lại "Lưu ý về ảnh"**

Thay toàn bộ nội dung mục `## Lưu ý về ảnh` (đến trước `## Thêm version mới`) bằng:

```markdown
## Lưu ý về ảnh

Bot tải ảnh từ Telegram về rồi upload thẳng lên Notion (File Upload API) — ảnh nằm hẳn trong Notion, không hết hạn. Workspace Notion free giới hạn 5 MB/ảnh; ảnh lớn hơn bị bỏ qua và bot báo lại.

Khi tạo GitHub issue, ảnh được commit vào branch `bug-assets` của repo (`bug-assets/BUG-12/...`) và nhúng vào issue. Repo private thì chỉ người có quyền vào repo xem được.

**Bug cũ** (trước bản này) lưu ảnh dạng link Telegram — link đó chứa token bot và hết hạn sau một thời gian. Sau khi cập nhật, nên **revoke token bot** (BotFather → `/revoke`) rồi điền token mới vào `.env`.
```

- [ ] **Step 6: README — cấu trúc thư mục**

Thay khối code trong mục `## Cấu trúc` bằng:

```
vltk-bot/
├── bot.py             # handler Telegram: lệnh group, phiên chat riêng, nút bấm
├── notion_client.py   # gọi Notion API, upload ảnh, format dữ liệu
├── issue_pipeline.py  # Notion → LLM → ảnh → GitHub issue → ghi ngược Notion
├── llm_client.py      # gọi LLM OpenAI-compatible (Qwen/DeepSeek), parse JSON
├── github_client.py   # tạo issue, commit ảnh vào branch bug-assets
├── issue_template.py  # dựng markdown issue theo template
├── issue_models.py    # dataclass dùng chung
├── config.py          # biến môi trường, tên property, danh sách option
├── tests/             # pytest (python -m pytest tests)
├── requirements.txt
├── .env.example
└── README.md
```

- [ ] **Step 7: Chạy toàn bộ test lần cuối**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: tất cả PASS

- [ ] **Step 8: Commit**

```bash
git add README.md .env.example env.example.txt
git commit -m "README: hướng dẫn GitHub issue tự động, ảnh lưu trên Notion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Smoke test tay** (cần người dùng: token thật, 4 cột Notion, branch `bug-assets`, `.env` đầy đủ)

Chạy `python bot.py` rồi làm lần lượt, ghi lại kết quả từng mục:

1. Chat riêng `/bug`, khai bug rõ ràng (đủ bước tái hiện) + 1 ảnh → issue tạo luôn; Notion có link ở cột GitHub Issue + dòng lịch sử "Tạo GitHub issue #n"; ảnh hiện trên Notion (không phải link Telegram) và trong issue.
2. `/bug` với mô tả "game lỗi", bước tái hiện Bỏ qua → bot hỏi; trả lời → issue; Notion có dòng "Bổ sung cho GitHub: …".
3. Như 2 nhưng gõ `/boqua` → issue tạo từ bản nháp.
4. Như 2 nhưng trong lúc bot "Đang soạn GitHub issue…" gửi thêm một tin → bot trả "⏳ Bot đang xử lý…", **không** có bug mới trên Notion.
5. Trong group `/bug Game lỗi` → thẻ hiện ngay, vài giây sau có nút Bổ sung; bấm Severity → nút Bổ sung vẫn còn; bấm Bổ sung → chat riêng hỏi → issue.
6. `/issue BUG-x` cho bug chưa có issue → tạo; chạy lại → "đã có GitHub issue".
7. `/issue` cho một bug cũ (trước bản này) → issue tạo được, ảnh cũ chết hiện "không tải được".
8. Xoá `LLM_API_KEY` khỏi `.env`, restart → `/bug` chạy như cũ, không có bước GitHub; `/issue` báo chưa cấu hình.
