"""Lớp bọc Notion API — tạo page, query, update status, upload ảnh."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

import config

log = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {config.NOTION_TOKEN}",
    "Notion-Version": config.NOTION_VERSION,
    "Content-Type": "application/json",
}

# Notion giới hạn ~3 request/giây. Semaphore + delay nhỏ để không bị 429.
_sem = asyncio.Semaphore(3)

# Trần số page kéo về khi query không giới hạn (limit=None) — tránh lặp vô tận.
_MAX_QUERY = 500


async def _request(method: str, path: str, **kwargs) -> dict[str, Any]:
    url = f"{config.NOTION_API}{path}"
    async with _sem:
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(3):
                resp = await client.request(method, url, headers=_HEADERS, **kwargs)
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


# ---------------------------------------------------------------- helpers

def _select(value: Optional[str]) -> dict:
    return {"select": {"name": value}} if value else {"select": None}


def _multi_select(values: Optional[list[str]]) -> dict:
    return {"multi_select": [{"name": v} for v in (values or [])]}


def _rich_text(value: Optional[str]) -> dict:
    if not value:
        return {"rich_text": []}
    return {"rich_text": [{"text": {"content": value[:2000]}}]}


def _title(value: str) -> dict:
    return {"title": [{"text": {"content": value[:2000]}}]}


def _plain(prop: Optional[dict]) -> str:
    """Đọc giá trị hiển thị của 1 property bất kỳ ra string."""
    if not prop:
        return ""
    t = prop.get("type")
    if t == "title" or t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get(t, []))
    if t == "select":
        sel = prop.get("select")
        return sel["name"] if sel else ""
    if t == "multi_select":
        return ", ".join(x["name"] for x in prop.get("multi_select", []))
    if t == "unique_id":
        uid = prop.get("unique_id") or {}
        prefix = uid.get("prefix") or ""
        num = uid.get("number")
        return f"{prefix}-{num}" if num is not None else ""
    if t == "created_time":
        return prop.get("created_time", "")[:10]
    if t == "last_edited_time":
        return prop.get("last_edited_time", "")[:10]
    return ""


def page_url(page_id: str) -> str:
    return f"https://www.notion.so/{page_id.replace('-', '')}"


def bug_db_url() -> str:
    return page_url(config.BUG_DB_ID)


# ---------------------------------------------------------------- create

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
    image_urls: Optional[list[str]] = None,
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
    }

    children = _text_block("heading_2", "Mô tả") + _paragraphs(description)
    if steps:
        children += _text_block("heading_2", "Bước tái hiện") + _paragraphs(steps)
    if image_urls:
        children += _text_block("heading_2", "Ảnh / Video")
        for url in image_urls:
            children.append({
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": url}},
            })
    children += _text_block("heading_2", HISTORY_HEADING)
    children += _history_item(f"Tạo bug · Mới báo cáo · bởi {reporter or '?'}")

    return await _request("POST", "/pages", json={
        "parent": {"database_id": config.BUG_DB_ID},
        "icon": {"type": "emoji", "emoji": "🐛"},
        "properties": props,
        "children": children[:100],
    })


async def create_feature(
    *,
    title: str,
    description: str,
    impact: Optional[str] = None,
    effort: Optional[str] = None,
    version: Optional[str] = None,
    modules: Optional[list[str]] = None,
    reporter: str = "",
    telegram_id: str = "",
    image_urls: Optional[list[str]] = None,
) -> dict[str, Any]:
    p = config.FEATURE_PROPS
    props = {
        p["title"]: _title(title),
        p["status"]: _select("Mới đề xuất"),
        p["impact"]: _select(impact),
        p["effort"]: _select(effort),
        p["version"]: _select(version),
        p["module"]: _multi_select(modules),
        p["reporter"]: _rich_text(reporter),
        p["telegram_id"]: _rich_text(telegram_id),
    }

    children = _text_block("heading_2", "Mô tả / Lý do") + _paragraphs(description)
    if image_urls:
        children += _text_block("heading_2", "Tham khảo")
        for url in image_urls:
            children.append({
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": url}},
            })

    return await _request("POST", "/pages", json={
        "parent": {"database_id": config.FEATURE_DB_ID},
        "icon": {"type": "emoji", "emoji": "💡"},
        "properties": props,
        "children": children[:100],
    })


def _text_block(block_type: str, text: str) -> list[dict]:
    return [{
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }]


def _paragraphs(text: str) -> list[dict]:
    """Chia text dài thành nhiều paragraph block (Notion giới hạn 2000 ký tự/block)."""
    blocks = []
    for line in (text or "").split("\n"):
        for i in range(0, max(len(line), 1), 1900):
            chunk = line[i:i + 1900]
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
            })
    return blocks


# ---------------------------------------------------------------- query

async def query_bugs(
    *,
    status: Optional[str] = None,
    version: Optional[str] = None,
    severity: Optional[str] = None,
    limit: Optional[int] = 20,
) -> list[dict]:
    """limit=None → kéo hết (theo next_cursor, trần _MAX_QUERY) để đếm được chính xác."""
    p = config.BUG_PROPS
    filters = []
    if status:
        filters.append({"property": p["status"], "select": {"equals": status}})
    if version:
        filters.append({"property": p["version_found"], "select": {"equals": version}})
    if severity:
        filters.append({"property": p["severity"], "select": {"equals": severity}})

    cap = _MAX_QUERY if limit is None else limit
    body: dict[str, Any] = {
        "page_size": min(cap, 100),
        "sorts": [
            {"property": p["priority"], "direction": "ascending"},
            {"timestamp": "created_time", "direction": "descending"},
        ],
    }
    if filters:
        body["filter"] = {"and": filters} if len(filters) > 1 else filters[0]

    results: list[dict] = []
    while True:
        data = await _request("POST", f"/databases/{config.BUG_DB_ID}/query", json=body)
        results.extend(data.get("results", []))
        if not data.get("has_more") or len(results) >= cap:
            break
        body["start_cursor"] = data["next_cursor"]
    return results[:cap]


async def query_features(
    *,
    status: Optional[str] = None,
    version: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    p = config.FEATURE_PROPS
    filters = []
    if status:
        filters.append({"property": p["status"], "select": {"equals": status}})
    if version:
        filters.append({"property": p["version"], "select": {"equals": version}})

    body: dict[str, Any] = {
        "page_size": min(limit, 100),
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }
    if filters:
        body["filter"] = {"and": filters} if len(filters) > 1 else filters[0]

    data = await _request("POST", f"/databases/{config.FEATURE_DB_ID}/query", json=body)
    return data.get("results", [])


async def find_by_short_id(db_id: str, id_prop: str, short_id: str) -> Optional[dict]:
    """Tìm page theo unique id kiểu BUG-12 hoặc chỉ '12'."""
    num_part = short_id.split("-")[-1]
    if not num_part.isdigit():
        return None
    body = {
        "filter": {"property": id_prop, "unique_id": {"equals": int(num_part)}},
        "page_size": 1,
    }
    data = await _request("POST", f"/databases/{db_id}/query", json=body)
    results = data.get("results", [])
    return results[0] if results else None


# ---------------------------------------------------------------- update

async def get_page(page_id: str) -> dict:
    return await _request("GET", f"/pages/{page_id}")


async def update_status(page_id: str, status_prop: str, new_status: str) -> dict:
    return await _request("PATCH", f"/pages/{page_id}", json={
        "properties": {status_prop: _select(new_status)}
    })


async def update_multi_select(page_id: str, prop_name: str, values: list[str]) -> dict:
    return await _request("PATCH", f"/pages/{page_id}", json={
        "properties": {prop_name: _multi_select(values)}
    })


async def update_property(page_id: str, prop_name: str, value: Optional[str]) -> dict:
    return await _request("PATCH", f"/pages/{page_id}", json={
        "properties": {prop_name: _select(value)}
    })


async def update_bug_status(
    page_id: str, status: str, version_fixed: Optional[str] = None
) -> dict:
    """Đổi Status bug, kèm Version fix nếu có — một request PATCH duy nhất.

    Không kiểm tra version với config.VERSIONS: Notion tự tạo option select mới.
    """
    p = config.BUG_PROPS
    props = {p["status"]: _select(status)}
    if version_fixed:
        props[p["version_fixed"]] = _select(version_fixed)
    return await _request("PATCH", f"/pages/{page_id}", json={"properties": props})


async def add_comment(page_id: str, text: str) -> str:
    """Ghi comment lên page. Trả về 'comment' hoặc 'callout' tuỳ cách ghi được.

    Comment API cần integration bật "Insert comments" (notion.so/my-integrations).
    Chưa bật → Notion trả 403; khi đó ghi thành callout ở cuối body page để
    không mất nội dung.
    """
    rich = [{"type": "text", "text": {"content": text[:2000]}}]
    try:
        await _request("POST", "/comments", json={
            "parent": {"page_id": page_id},
            "rich_text": rich,
        })
        return "comment"
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 403:
            raise
        log.warning("Integration chưa có quyền Insert comments — ghi callout thay thế")

    await _request("PATCH", f"/blocks/{page_id}/children", json={
        "children": [{
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": rich,
                "icon": {"type": "emoji", "emoji": "🔁"},
            },
        }],
    })
    return "callout"


# ---------------------------------------------------------------- lịch sử

HISTORY_HEADING = "📜 Lịch sử"
_VN_TZ = timezone(timedelta(hours=7))


def _history_item(text: str) -> list[dict]:
    stamp = datetime.now(_VN_TZ).strftime("%d/%m/%Y %H:%M")
    return [{
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [
            {"type": "text", "text": {"content": f"{stamp} — "},
             "annotations": {"code": True}},
            {"type": "text", "text": {"content": text[:1900]}},
        ]},
    }]


async def _has_history_heading(page_id: str) -> bool:
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        data = await _request("GET", f"/blocks/{page_id}/children", params=params)
        for b in data.get("results", []):
            if b.get("type") == "heading_2":
                txt = "".join(x.get("plain_text", "") for x in b["heading_2"].get("rich_text", []))
                if txt.strip() == HISTORY_HEADING:
                    return True
        if not data.get("has_more"):
            return False
        cursor = data.get("next_cursor")


async def log_history(page_id: str, text: str) -> None:
    """Thêm 1 dòng vào mục "📜 Lịch sử" cuối page (tạo heading nếu page cũ chưa có).

    Dùng cho mọi thao tác bot làm với bug: đổi status, sửa field, reopen...
    Lỗi ở đây không nên làm hỏng thao tác chính — caller nên try/except.
    """
    children: list[dict] = []
    if not await _has_history_heading(page_id):
        children += _text_block("heading_2", HISTORY_HEADING)
    children += _history_item(text)
    await _request("PATCH", f"/blocks/{page_id}/children", json={"children": children})


# ---------------------------------------------------------------- format

def format_bug_line(page: dict) -> str:
    props = page.get("properties", {})
    p = config.BUG_PROPS
    bug_id = _plain(props.get(p["id"])) or "?"
    title = _plain(props.get(p["title"])) or "(chưa có tiêu đề)"
    status = _plain(props.get(p["status"]))
    sev = _plain(props.get(p["severity"]))
    pri = _plain(props.get(p["priority"]))
    ver = _plain(props.get(p["version_found"]))

    bits = [config.SEVERITY_EMOJI.get(sev, "⚪"), f"<b>{bug_id}</b>", title]
    meta = " · ".join(x for x in [
        f"{config.STATUS_EMOJI.get(status, '')} {status}".strip(),
        pri, ver
    ] if x)
    return " ".join(bits) + (f"\n   <i>{meta}</i>" if meta else "")


def format_feature_line(page: dict) -> str:
    props = page.get("properties", {})
    p = config.FEATURE_PROPS
    fr_id = _plain(props.get(p["id"])) or "?"
    title = _plain(props.get(p["title"])) or "(chưa có tên)"
    status = _plain(props.get(p["status"]))
    impact = _plain(props.get(p["impact"]))
    effort = _plain(props.get(p["effort"]))
    ver = _plain(props.get(p["version"]))

    meta = " · ".join(x for x in [
        f"{config.STATUS_EMOJI.get(status, '')} {status}".strip(),
        f"Impact: {impact}" if impact else "",
        f"Effort: {effort}" if effort else "",
        ver,
    ] if x)
    return f"💡 <b>{fr_id}</b> {title}" + (f"\n   <i>{meta}</i>" if meta else "")


def get_title(page: dict, title_prop: str) -> str:
    return _plain(page.get("properties", {}).get(title_prop)) or "(không tên)"


def get_short_id(page: dict, id_prop: str) -> str:
    return _plain(page.get("properties", {}).get(id_prop)) or "?"


def get_prop(page: dict, prop_name: str) -> str:
    return _plain(page.get("properties", {}).get(prop_name))
