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
