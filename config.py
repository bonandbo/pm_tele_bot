"""Cấu hình bot — đọc từ biến môi trường (.env)."""
import os
import re
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

# Group được phép dùng bot. Chat ID group là số âm, vd -1001234567890.
# Cách nhau bởi dấu phẩy. Để trống = bot chạy ở mọi group được add vào.
_groups = os.getenv("ALLOWED_CHAT_IDS", "").strip()
ALLOWED_CHAT_IDS = {
    int(x.strip()) for x in _groups.split(",")
    if x.strip().lstrip("-").isdigit()
}

# Danh sách version. Thêm build mới ở đây VÀ thêm option tương ứng trong Notion.
VERSIONS = ["v1.0", "v1.1", "v1.2"]

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
    "character": "Nhân vật",
    "level": "Cấp",
    "map": "Bản đồ",
    "github_issue": "GitHub Issue",
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
    "Mới báo cáo", "Đã xác nhận", "Đang fix", "Đang làm",
    "Chờ verify", "Đã fix", "Confirmed", "Không fix", "Trùng lặp",
]
# Luồng 4 cột trên board Notion: Open → Đang làm → Đã fix → Confirmed.
# Dùng bởi /fixbug, /fixed, /confirmed, /reopened và các cờ của /bugs.
BUG_FLOW = {
    "open": "Mới báo cáo",
    "doing": "Đang làm",
    "fixed": "Đã fix",
    "confirmed": "Confirmed",
}
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
    "Chờ verify": "🔍", "Đã fix": "🎉", "Confirmed": "☑️",
    "Không fix": "🚫", "Trùng lặp": "♻️",
    "Mới đề xuất": "🆕", "Đang xem xét": "🤔", "Đã duyệt": "👍",
    "Đang làm": "🔨", "Hoàn thành": "🎉", "Từ chối": "❌", "Hoãn lại": "⏸️",
}

SEVERITY_EMOJI = {
    "Nghiêm trọng": "🔴", "Cao": "🟠", "Trung bình": "🟡", "Thấp": "⚪",
}

# ---- LLM (OpenAI-compatible: DashScope/Qwen, DeepSeek) — tạo GitHub issue ----
# DashScope quốc tế: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
# DeepSeek:          https://api.deepseek.com
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
).strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip()


def default_disable_thinking(base_url: str, raw: str) -> bool:
    """Qwen3 trên DashScope bật "thinking" sẵn → 50s+/lần, dễ timeout. Mặc định tắt khi dùng DashScope;
    nhà cung cấp khác không gửi tham số (tránh lỗi tham số lạ). LLM_DISABLE_THINKING=1/0 để ghi đè."""
    raw = (raw or "").strip().lower()
    if raw:
        return raw in ("1", "true", "yes")
    return "dashscope" in base_url.lower()


LLM_DISABLE_THINKING = default_disable_thinking(LLM_BASE_URL, os.getenv("LLM_DISABLE_THINKING", ""))

# ---- GitHub issue cho AI agent ----
def normalize_github_repo(raw: str) -> str:
    """'https://github.com/owner/repo.git', 'git@github.com:owner/repo.git' → 'owner/repo'."""
    repo = (raw or "").strip()
    repo = re.sub(r"^(?:git@github\.com:|(?:https?://)?(?:www\.)?github\.com/)", "", repo)
    repo = repo.rstrip("/")
    return repo[:-4] if repo.endswith(".git") else repo


# Token fine-grained, chỉ 1 repo, quyền Issues: write + Contents: write.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
# owner/repo — dán nguyên URL repo cũng được, tự quy về owner/repo
GITHUB_REPO = normalize_github_repo(os.getenv("GITHUB_REPO", ""))
GITHUB_LABELS = [
    x.strip() for x in os.getenv("GITHUB_LABELS", "bug").split(",") if x.strip()
]
# Branch riêng chứa ảnh bug — tạo tay 1 lần (xem README)
GITHUB_ASSETS_BRANCH = os.getenv("GITHUB_ASSETS_BRANCH", "bug-assets").strip()

# Thiếu bất kỳ biến nào → tắt tính năng, bot chạy như cũ
GITHUB_ENABLED = all([LLM_API_KEY, LLM_MODEL, GITHUB_TOKEN, GITHUB_REPO])
