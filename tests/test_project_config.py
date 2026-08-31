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
