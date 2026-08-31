"""Gist publishing logic, tested with mocked HTTP calls — no real GitHub
account or token needed. Config isolation comes from conftest.isolated_config
(autouse), so these never touch a real ~/.foxygpu/config.json."""

from types import SimpleNamespace
from unittest import mock

import pytest

from foxygpu import github


def _fake_resp(status_code, json_data=None):
    r = SimpleNamespace()
    r.status_code = status_code
    r.ok = status_code < 400
    r.text = f"fake body for {status_code}"
    r._json = json_data or {}
    r.json = lambda: r._json

    def raise_for_status():
        if status_code >= 400:
            raise Exception(f"HTTP {status_code}")

    r.raise_for_status = raise_for_status
    return r


def test_first_publish_creates_a_gist():
    with mock.patch.object(github.requests, "post") as post, mock.patch.object(
        github.requests, "patch"
    ) as patch:
        post.return_value = _fake_resp(
            201, {"id": "abc123", "html_url": "https://gist.github.com/someuser/abc123"}
        )
        gist_id, colab_url = github.publish_notebook("FAKE_TOKEN", "{}")

    assert post.called
    assert not patch.called
    assert gist_id == "abc123"
    assert colab_url == "https://colab.research.google.com/gist/someuser/abc123"


def test_second_publish_updates_the_existing_gist():
    with mock.patch.object(github.requests, "post") as post:
        post.return_value = _fake_resp(
            201, {"id": "abc123", "html_url": "https://gist.github.com/someuser/abc123"}
        )
        github.publish_notebook("FAKE_TOKEN", "{}")

    with mock.patch.object(github.requests, "post") as post, mock.patch.object(
        github.requests, "patch"
    ) as patch:
        patch.return_value = _fake_resp(
            200, {"id": "abc123", "html_url": "https://gist.github.com/someuser/abc123"}
        )
        github.publish_notebook("FAKE_TOKEN", "{}")

    assert patch.called
    assert not post.called


def test_stale_gist_id_falls_back_to_creating_a_new_one():
    with mock.patch.object(github.requests, "post") as post:
        post.return_value = _fake_resp(
            201, {"id": "abc123", "html_url": "https://gist.github.com/someuser/abc123"}
        )
        github.publish_notebook("FAKE_TOKEN", "{}")

    with mock.patch.object(github.requests, "post") as post, mock.patch.object(
        github.requests, "patch"
    ) as patch:
        patch.return_value = _fake_resp(404)
        post.return_value = _fake_resp(
            201, {"id": "newgist456", "html_url": "https://gist.github.com/someuser/newgist456"}
        )
        gist_id, _ = github.publish_notebook("FAKE_TOKEN", "{}")

    assert patch.called
    assert post.called
    assert gist_id == "newgist456"


def test_401_raises_clear_system_exit():
    with mock.patch.object(github.requests, "post") as post:
        post.return_value = _fake_resp(401)
        with pytest.raises(SystemExit) as exc_info:
            github.publish_notebook("BAD_TOKEN", "{}")
    assert "401" in str(exc_info.value)


def test_fresh_404_surfaces_classic_token_guidance():
    """A 404 on first publish (no existing gist) is the classic symptom of a
    fine-grained token, which doesn't support the Gists API at all."""
    with mock.patch.object(github.requests, "post") as post:
        post.return_value = _fake_resp(404)
        with pytest.raises(SystemExit) as exc_info:
            github.publish_notebook("FINEGRAINED_TOKEN", "{}")
    assert "classic" in str(exc_info.value).lower()
