import pytest

import mpc_iml


def test_version() -> None:
    assert mpc_iml.__version__ == "0.1.0"


@pytest.mark.hardware
def test_mpc_connected_placeholder() -> None:
    """Placeholder until the input interface exists; run by a human with the MPC connected."""
    pytest.skip("No hardware test is implemented yet.")
