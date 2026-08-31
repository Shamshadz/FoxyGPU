import sys
import time

import pytest

from foxygpu.client import AgentClient


def test_unreachable_agent_raises_friendly_error_not_raw_traceback():
    client = AgentClient("http://127.0.0.1:1", "fake-token")  # port 1: nothing listens there
    with pytest.raises(SystemExit) as exc_info:
        client.list_processes()
    assert "Could not reach" in str(exc_info.value)


def test_latest_process_port_none_when_no_processes(agent_server):
    base_url, token = agent_server
    client = AgentClient(base_url, token)
    assert client.latest_process_port() is None


def test_latest_process_port_returns_most_recently_started(agent_server, upload_project):
    base_url, token = agent_server
    client = AgentClient(base_url, token)
    project_id = upload_project().json()["project_id"]

    client.start_process(project_id, f'{sys.executable} -c "import time; time.sleep(5)"')
    time.sleep(0.2)
    _, second_port = client.start_process(
        project_id, f'{sys.executable} -c "import time; time.sleep(5)"'
    )

    assert client.latest_process_port() == second_port
