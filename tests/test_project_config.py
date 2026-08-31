import pytest

from foxygpu.project_config import (
    CONFIG_FILENAME,
    ProjectConfigError,
    load_project_config,
    write_project_config,
)


def test_no_config_file_returns_none(tmp_path):
    assert load_project_config(tmp_path) is None


def test_missing_command_field_raises(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text("runtime: colab\ngpu: true\n")
    with pytest.raises(ProjectConfigError, match="command"):
        load_project_config(tmp_path)


def test_unsupported_runtime_raises(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text("runtime: runpod\ncommand: echo hi\n")
    with pytest.raises(ProjectConfigError, match="runpod"):
        load_project_config(tmp_path)


def test_invalid_yaml_raises_clear_error(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text("command: [unterminated\n")
    with pytest.raises(ProjectConfigError):
        load_project_config(tmp_path)


def test_non_mapping_yaml_raises(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text("- just\n- a\n- list\n")
    with pytest.raises(ProjectConfigError, match="mapping"):
        load_project_config(tmp_path)


def test_valid_config_loads_with_defaults(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text("command: python app.py\n")
    config = load_project_config(tmp_path)
    assert config.command == "python app.py"
    assert config.runtime == "colab"
    assert config.gpu is True
    assert config.name is None
    assert config.expose is True


def test_valid_config_respects_all_fields(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text(
        "runtime: colab\ngpu: false\ncommand: python app.py\nname: myapp\nexpose: false\n"
    )
    config = load_project_config(tmp_path)
    assert config.gpu is False
    assert config.name == "myapp"
    assert config.expose is False


def test_write_then_load_roundtrip(tmp_path):
    cmd = "pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port $PORT"
    write_project_config(tmp_path, cmd, name="myapp")
    config = load_project_config(tmp_path)
    assert config.command == cmd
    assert config.name == "myapp"
    assert config.runtime == "colab"
    assert config.gpu is True


def test_write_handles_commands_with_special_yaml_characters(tmp_path):
    # colons, quotes, and && are all things a shell command legitimately
    # contains that could confuse a hand-rolled (non-yaml-library) writer.
    cmd = 'echo "hello: world" && python -c "print(1)"'
    write_project_config(tmp_path, cmd)
    config = load_project_config(tmp_path)
    assert config.command == cmd


def test_no_env_or_env_file_gives_empty_dict(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text("command: echo hi\n")
    config = load_project_config(tmp_path)
    assert config.env == {}


def test_inline_env_mapping(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text(
        "command: echo hi\nenv:\n  FOO: bar\n  BAZ: qux\n"
    )
    config = load_project_config(tmp_path)
    assert config.env == {"FOO": "bar", "BAZ": "qux"}


def test_env_file_is_loaded_relative_to_project_root(tmp_path):
    (tmp_path / ".env").write_text("DATABASE_URL=postgres://localhost/db\n")
    (tmp_path / CONFIG_FILENAME).write_text("command: echo hi\nenv_file: .env\n")
    config = load_project_config(tmp_path)
    assert config.env == {"DATABASE_URL": "postgres://localhost/db"}


def test_inline_env_overrides_env_file_on_conflict(tmp_path):
    (tmp_path / ".env").write_text("FOO=from_file\nSHARED=file_value\n")
    (tmp_path / CONFIG_FILENAME).write_text(
        "command: echo hi\nenv_file: .env\nenv:\n  SHARED: inline_value\n"
    )
    config = load_project_config(tmp_path)
    assert config.env == {"FOO": "from_file", "SHARED": "inline_value"}


def test_missing_env_file_raises_clear_error(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text("command: echo hi\nenv_file: nope.env\n")
    with pytest.raises(ProjectConfigError, match="not found"):
        load_project_config(tmp_path)


def test_non_mapping_env_raises(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text("command: echo hi\nenv: not_a_mapping\n")
    with pytest.raises(ProjectConfigError, match="env"):
        load_project_config(tmp_path)
