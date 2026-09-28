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
