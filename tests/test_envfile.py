import pytest

from foxygpu.envfile import EnvFileError, parse_env_file


def test_missing_file_raises(tmp_path):
    with pytest.raises(EnvFileError, match="not found"):
        parse_env_file(tmp_path / "does_not_exist.env")


def test_basic_key_value_pairs(tmp_path):
    f = tmp_path / ".env"
    f.write_text("FOO=bar\nBAZ=qux\n")
    assert parse_env_file(f) == {"FOO": "bar", "BAZ": "qux"}


def test_blank_lines_and_comments_ignored(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# a comment\n\nFOO=bar\n  # indented comment\nBAZ=qux\n\n")
    assert parse_env_file(f) == {"FOO": "bar", "BAZ": "qux"}


def test_quoted_values_are_unquoted(tmp_path):
    f = tmp_path / ".env"
    f.write_text('FOO="bar baz"\nSINGLE=\'quoted value\'\n')
    assert parse_env_file(f) == {"FOO": "bar baz", "SINGLE": "quoted value"}


def test_value_with_equals_sign_preserved(tmp_path):
    f = tmp_path / ".env"
    f.write_text("DATABASE_URL=postgres://user:pass@host/db?opt=val\n")
    assert parse_env_file(f) == {"DATABASE_URL": "postgres://user:pass@host/db?opt=val"}


def test_empty_value_allowed(tmp_path):
    f = tmp_path / ".env"
    f.write_text("EMPTY=\n")
    assert parse_env_file(f) == {"EMPTY": ""}


def test_line_without_equals_raises_with_line_number(tmp_path):
    f = tmp_path / ".env"
    f.write_text("FOO=bar\nNOTVALID\n")
    with pytest.raises(EnvFileError, match=r"\.env:2"):
        parse_env_file(f)


def test_empty_key_raises(tmp_path):
    f = tmp_path / ".env"
    f.write_text("=novalue\n")
    with pytest.raises(EnvFileError):
        parse_env_file(f)


def test_whitespace_around_key_and_value_stripped(tmp_path):
    f = tmp_path / ".env"
    f.write_text("  FOO  =  bar  \n")
    assert parse_env_file(f) == {"FOO": "bar"}
