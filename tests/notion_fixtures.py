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
