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
