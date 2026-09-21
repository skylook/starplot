import os
import subprocess
import sys

from starplot import data, config


def test_data_path(tmp_path):
    settings_before = config.settings
    load_before = data.load
    data_path = tmp_path / "data"
    env = os.environ.copy()
    env["STARPLOT_DATA_PATH"] = str(data_path)

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
from pathlib import Path

from starplot import config, data

expected = Path(os.environ["STARPLOT_DATA_PATH"])
if config.settings.data_path != expected:
    raise AssertionError("settings did not use STARPLOT_DATA_PATH")
if Path(data.load.directory) != expected:
    raise AssertionError("Skyfield loader did not use STARPLOT_DATA_PATH")
if not expected.is_dir():
    raise AssertionError("Skyfield loader did not create the data directory")
""",
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

    assert data_path.is_dir()
    assert config.settings is settings_before
    assert data.load is load_before
