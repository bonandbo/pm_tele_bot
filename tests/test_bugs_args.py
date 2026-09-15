"""Test parse tham số /bugs: cờ -open/-fixing/-fixed/-confirmed + version (thuần, không mạng)."""
import bot
import config

FLOW = config.BUG_FLOW


def test_no_args_defaults_to_open():
    assert bot._parse_bugs_args([]) == (FLOW["open"], None, None)


def test_flags_map_to_board_columns():
    assert bot._parse_bugs_args(["-open"]) == (FLOW["open"], None, None)
    assert bot._parse_bugs_args(["-fixing"]) == (FLOW["doing"], None, None)
    assert bot._parse_bugs_args(["-fixed"]) == (FLOW["fixed"], None, None)
    assert bot._parse_bugs_args(["-confirmed"]) == (FLOW["confirmed"], None, None)


def test_flag_is_case_insensitive_and_accepts_double_dash():
    assert bot._parse_bugs_args(["-FIXED"]) == (FLOW["fixed"], None, None)
    assert bot._parse_bugs_args(["--fixing"]) == (FLOW["doing"], None, None)


def test_legacy_open_aliases_still_work():
    for alias in ("open", "mở", "chưa"):
        assert bot._parse_bugs_args([alias]) == (FLOW["open"], None, None)


def test_flag_combines_with_version():
    assert bot._parse_bugs_args(["-fixed", "v1.3"]) == (FLOW["fixed"], "v1.3", None)
    assert bot._parse_bugs_args(["v1.3", "-fixed"]) == (FLOW["fixed"], "v1.3", None)


def test_version_alone_keeps_open_default():
    assert bot._parse_bugs_args(["v1.2"]) == (FLOW["open"], "v1.2", None)


def test_explicit_status_name_still_works():
    assert bot._parse_bugs_args(["Đang", "fix"]) == ("Đang fix", None, None)


def test_unknown_flag_returns_error():
    status, version, err = bot._parse_bugs_args(["-foo"])
    assert status is None and version is None
    assert "-foo" in err
