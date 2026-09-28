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
