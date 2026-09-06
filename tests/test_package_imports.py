from vhs_restore import __version__


def test_version_string():
    assert isinstance(__version__, str) and __version__
