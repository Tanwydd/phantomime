"""Smoke tests: import, instantiate, version check."""

import phantomime
from phantomime import HumanBrowser, run_swarm, run_swarm_multiprocess


def test_version_string():
    assert isinstance(phantomime.__version__, str)
    assert phantomime.__version__ == "9.0.0"


def test_exports_present():
    assert HumanBrowser is not None
    assert run_swarm is not None
    assert run_swarm_multiprocess is not None


def test_humanbrowser_instantiates(tmp_path):
    browser = HumanBrowser(profile_dir=str(tmp_path / "profile"), headless=True)
    assert browser is not None
    assert browser.locale == "es-ES"


def test_humanbrowser_custom_params(tmp_path):
    browser = HumanBrowser(
        profile_dir=str(tmp_path / "profile2"),
        headless=True,
        locale="en-US",
        timezone="America/New_York",
        typo_rate=0.0,
        frustration_rate=0.0,
    )
    assert browser.locale == "en-US"
    assert browser.timezone == "America/New_York"
    assert browser.typo_rate == 0.0
