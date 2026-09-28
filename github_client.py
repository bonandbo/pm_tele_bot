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
