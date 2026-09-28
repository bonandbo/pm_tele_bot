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
