import pytest

from support import running_server


@pytest.fixture
def server(tmp_path):
    with running_server(tmp_path / "data") as url:
        yield url
