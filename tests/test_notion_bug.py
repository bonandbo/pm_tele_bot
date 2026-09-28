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


def test_create_bug_omits_empty_new_props(monkeypatch):
    """DB chưa thêm cột Nhân vật/Cấp/Bản đồ vẫn phải lưu được bug báo nhanh (Notion 400 nếu gửi cột lạ)."""
    pages = []

    def handler(request):
        pages.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "p1", "properties": {}})

    _mock(monkeypatch, handler)
    asyncio.run(nc.create_bug(title="T", description="D"))
    props = pages[0]["properties"]
    for key in ("character", "level", "map", "github_issue"):
        assert P[key] not in props, key
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
