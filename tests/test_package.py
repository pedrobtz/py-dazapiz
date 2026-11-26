from importlib.metadata import version

import dazapiz


def test_version_matches_metadata():
    assert dazapiz.__version__ == version("dazapiz")
