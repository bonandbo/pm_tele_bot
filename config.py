"""Cấu hình bot — đọc từ biến môi trường (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()


def _required(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Thiếu biến môi trường bắt buộc: {key}. Xem file .env.example")
    return val


TELEGRAM_TOKEN = _required("TELEGRAM_TOKEN")
NOTION_TOKEN = _required("NOTION_TOKEN")

BUG_DB_ID = _required("BUG_DB_ID")
FEATURE_DB_ID = _required("FEATURE_DB_ID")

# Chat ID của group/admin nhận thông báo. Để trống nếu không dùng.
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

# Chỉ những Telegram user ID này được đổi status / xoá. Cách nhau bởi dấu phẩy.
# Để trống = ai cũng đổi được (không khuyến khích).
_admins = os.getenv("ADMIN_USER_IDS", "").strip()
ADMIN_USER_IDS = {int(x) for x in _admins.split(",") if x.strip().isdigit()}

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"

# ---- Tên property trong Notion. Sửa ở đây nếu đổi tên cột trong Notion ----
BUG_PROPS = {
    "title": "Tiêu đề",
    "id": "Bug ID",
    "status": "Status",
    "severity": "Severity",
    "priority": "Priority",
    "version_found": "Version phát hiện",
    "version_fixed": "Version fix",
    "module": "Module",
    "reporter": "Người báo cáo",
    "telegram_id": "Telegram ID",
}

FEATURE_PROPS = {
    "title": "Tên feature",
    "id": "FR ID",
    "status": "Status",
    "impact": "Impact",
    "effort": "Effort",
    "version": "Version dự kiến",
    "module": "Module",
    "reporter": "Người đề xuất",
    "telegram_id": "Telegram ID",
}

# ---- Giá trị select (phải khớp option trong Notion) ----
BUG_STATUSES = [
    "Mới báo cáo", "Đã xác nhận", "Đang fix",
    "Chờ verify", "Đã fix", "Không fix", "Trùng lặp",
]
FEATURE_STATUSES = [
    "Mới đề xuất", "Đang xem xét", "Đã duyệt",
    "Đang làm", "Hoàn thành", "Từ chối", "Hoãn lại",
]
SEVERITIES = ["Nghiêm trọng", "Cao", "Trung bình", "Thấp"]
PRIORITIES = ["P0", "P1", "P2", "P3"]
IMPACTS = ["Cao", "Trung bình", "Thấp"]
EFFORTS = ["Lớn", "Trung bình", "Nhỏ"]
MODULES = [
    "Client", "Server", "Combat", "UI/UX",
    "Kinh tế/Shop", "Nhiệm vụ", "Event", "Login/Account",
]

STATUS_EMOJI = {
    "Mới báo cáo": "🆕", "Đã xác nhận": "✅", "Đang fix": "🔧",
    "Chờ verify": "🔍", "Đã fix": "🎉", "Không fix": "🚫", "Trùng lặp": "♻️",
    "Mới đề xuất": "🆕", "Đang xem xét": "🤔", "Đã duyệt": "👍",
    "Đang làm": "🔨", "Hoàn thành": "🎉", "Từ chối": "❌", "Hoãn lại": "⏸️",
}

SEVERITY_EMOJI = {
    "Nghiêm trọng": "🔴", "Cao": "🟠", "Trung bình": "🟡", "Thấp": "⚪",
}
