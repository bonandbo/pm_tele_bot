"""Test các hàm thuần trong bot.py cho luồng GitHub issue (không gọi mạng)."""
import bot


def test_too_big():
    assert bot._too_big(None) is False
    assert bot._too_big(0) is False
    assert bot._too_big(bot.MAX_IMAGE_BYTES) is False
    assert bot._too_big(bot.MAX_IMAGE_BYTES + 1) is True


def test_parse_level():
    assert bot._parse_level("90") == 90
    assert bot._parse_level(" cấp 90 ") == 90
    assert bot._parse_level("Cấp90") == 90
    assert bot._parse_level("Lv.120") == 120
    assert bot._parse_level("lv 5") == 5
    assert bot._parse_level("level 7") == 7


def test_parse_level_rejects_garbage():
    for text in ("", "abc", "0", "90 thiếu lâm", "-5", "12345", "1000"):
        assert bot._parse_level(text) is None, text


def test_issue_number():
    assert bot._issue_number("https://github.com/t/g/issues/34") == "34"
    assert bot._issue_number("https://github.com/t/g/issues/34/") == "34"


def test_clarify_payload_and_url(monkeypatch):
    monkeypatch.setattr(bot, "BOT_USERNAME", "vltk_bot")
    assert bot._clarify_payload("BUG-12") == "clarify_12"
    assert bot._clarify_url("BUG-12") == "https://t.me/vltk_bot?start=clarify_12"


def test_fail_text_escapes_and_mentions_issue_command():
    text = bot._fail_text("BUG-7", Exception("LLM trả lỗi <500>"))
    assert "&lt;500&gt;" in text
    assert "/issue BUG-7" in text


def test_conversation_has_waiting_state_and_nonblocking_slow_handlers():
    from telegram.ext import ConversationHandler

    conv = bot._build_conversation()
    assert ConversationHandler.WAITING in conv.states
    assert ConversationHandler.TIMEOUT in conv.states
    assert bot.BUG_CLARIFY in conv.states
    slow = {bot.bug_image, bot.bug_clarify, bot.bug_clarify_skip, bot.start_or_deeplink}
    handlers = [h for hs in conv.states.values() for h in hs] + list(conv.entry_points)
    found = {h.callback for h in handlers if h.callback in slow}
    assert found == slow
    for h in handlers:
        if h.callback in slow:
            assert h.block is False, h.callback.__name__


from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from notion_fixtures import bug_page, url_prop


def _urls(kb):
    return [b.url for row in kb.inline_keyboard for b in row if b.url]


def test_bug_card_buttons():
    issue = "https://github.com/t/g/issues/34"
    clarify = "https://t.me/vltk_bot?start=clarify_12"

    _, kb = bot._bug_card(bug_page())
    assert issue not in _urls(kb) and clarify not in _urls(kb)

    _, kb = bot._bug_card(bug_page(github_issue=url_prop(issue)))
    assert issue in _urls(kb)

    _, kb = bot._bug_card(bug_page(), clarify_url=clarify)
    assert clarify in _urls(kb)

    # Đã có issue thì không hiện nút Bổ sung nữa
    _, kb = bot._bug_card(bug_page(github_issue=url_prop(issue)), clarify_url=clarify)
    assert issue in _urls(kb) and clarify not in _urls(kb)


def test_clarify_button_url_found():
    clarify = "https://t.me/vltk_bot?start=clarify_12"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟠 Cao", callback_data="sv|x|1")],
        [InlineKeyboardButton("✍️ Bổ sung cho GitHub issue", url=clarify)],
    ])
    assert bot._clarify_button_url(markup) == clarify


def test_clarify_button_url_absent():
    assert bot._clarify_button_url(None) is None
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📄 Notion", url="https://notion.so/x")]])
    assert bot._clarify_button_url(markup) is None


# ---------------------------------------------------------------- lỗi mạng giữa luồng GitHub không được làm kẹt hội thoại

import asyncio
from types import SimpleNamespace

from telegram.error import NetworkError
from telegram.ext import ConversationHandler

from issue_models import BugInput, Draft, IssueFields


class _Msg:
    """Message giả: reply_text / send_action ném NetworkError nếu được yêu cầu."""

    def __init__(self, text="", fail=()):
        self.text = text
        self.fail = set(fail)
        self.sent = []
        self.chat = SimpleNamespace(send_action=self._send_action)

    async def _send_action(self, *args, **kwargs):
        if "send_action" in self.fail:
            raise NetworkError("mạng chập chờn")

    async def reply_text(self, text, **kwargs):
        if "reply_text" in self.fail:
            raise NetworkError("mạng chập chờn")
        self.sent.append(text)


def _gh_user_data():
    bug = BugInput(page_id="page-1", bug_id="BUG-12", notion_url="u", title="T")
    draft = Draft("need_info", ["Lỗi xảy ra lúc nào?"], IssueFields(title="T", symptom="S"))
    return {"gh_bug": bug, "gh_draft": draft, "gh_questions": draft.questions, "gh_rounds": 1}


def test_clarify_network_error_keeps_clarify_state(monkeypatch):
    """Còn bản nháp → giữ BUG_CLARIFY để timeout vẫn tự tạo issue, không kẹt ở state cũ."""
    async def no_history(pid, text):
        pass
    monkeypatch.setattr(bot.nc, "log_history", no_history)
    update = SimpleNamespace(message=_Msg(text="lúc vào map", fail={"send_action"}))
    context = SimpleNamespace(user_data=_gh_user_data())
    assert asyncio.run(bot.bug_clarify(update, context)) == bot.BUG_CLARIFY


def test_clarify_entry_network_error_ends_conversation(monkeypatch):
    """Chưa có bản nháp → kết thúc hội thoại sạch sẽ thay vì kẹt."""
    async def find(db, prop, short_id):
        return {"id": "page-1"}
    monkeypatch.setattr(bot.ip, "enabled", lambda: True)
    monkeypatch.setattr(bot.nc, "find_by_short_id", find)
    update = SimpleNamespace(message=_Msg(fail={"reply_text"}))
    context = SimpleNamespace(user_data={"title": "cũ"})
    assert asyncio.run(bot._gh_guard(context, bot._clarify_entry(update, context, "12"))) == ConversationHandler.END
    assert "gh_bug" not in context.user_data
