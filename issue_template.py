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
