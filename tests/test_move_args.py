"""Test phần parse tham số của /fixbug, /fixed, /confirmed, /reopened (thuần, không gọi mạng)."""
import bot


def test_parse_bug_id_and_rest():
    assert bot._parse_bug_args(["BUG-44", "v1.3"]) == ("BUG-44", "v1.3")


def test_parse_bug_id_lowercase_is_uppercased():
    assert bot._parse_bug_args(["bug-44"]) == ("BUG-44", "")


def test_parse_bare_number_gets_prefix():
    assert bot._parse_bug_args(["44"]) == ("BUG-44", "")


def test_parse_rest_keeps_multiword_reason():
    assert bot._parse_bug_args(["BUG-7", "vẫn", "còn", "crash"]) == ("BUG-7", "vẫn còn crash")


def test_parse_empty_args():
    assert bot._parse_bug_args([]) == (None, "")


def test_parse_rejects_non_bug_id():
    assert bot._parse_bug_args(["FR-3"]) == (None, "")
    assert bot._parse_bug_args(["abc"]) == (None, "")


def test_normalize_version_adds_v_prefix():
    assert bot._normalize_version("1.3") == "v1.3"


def test_normalize_version_keeps_existing_prefix():
    assert bot._normalize_version("v1.3") == "v1.3"
    assert bot._normalize_version("V0.0.8") == "v0.0.8"


def test_normalize_version_empty():
    assert bot._normalize_version("") is None
    assert bot._normalize_version("   ") is None


def test_normalize_version_rejects_text_without_digits():
    assert bot._normalize_version("ok") is None
    assert bot._normalize_version("v") is None
