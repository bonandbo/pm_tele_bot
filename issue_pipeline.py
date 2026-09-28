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
    gh_prop = config.BUG_PROPS["github_issue"]
    if gh_prop not in page.get("properties", {}):
        # Không có cột thì không ghi ngược được link → mỗi lần chạy lại sẽ tạo issue trùng
        raise PipelineError(f"Notion chưa có cột '{gh_prop}' (kiểu URL) trong Bug Tracker")
    existing = nc.get_prop(page, gh_prop)
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
