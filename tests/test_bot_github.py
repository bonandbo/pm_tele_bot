"""Test các hàm thuần trong bot.py cho luồng GitHub issue (không gọi mạng)."""
import bot


def test_too_big():
    assert bot._too_big(None) is False
    assert bot._too_big(0) is False
    assert bot._too_big(bot.MAX_IMAGE_BYTES) is False
    assert bot._too_big(bot.MAX_IMAGE_BYTES + 1) is True
