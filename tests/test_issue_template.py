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
