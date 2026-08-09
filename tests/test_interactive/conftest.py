import matplotlib.pyplot as plt
import pytest


@pytest.fixture(autouse=True)
def _close_matplotlib_figures():
    """Keep interactive tests from accumulating open Matplotlib figures."""
    plt.close("all")
    yield
    plt.close("all")
