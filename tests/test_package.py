from importlib.metadata import version

import dazure


def test_version_matches_metadata():
    assert dazure.__version__ == version("dazure")
