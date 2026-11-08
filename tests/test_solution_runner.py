"""scripts/solution.sh must run a solution's package, not the learner's src/ copy."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def fake_solution():
    pkg = REPO / "solutions" / "day-99" / "netops_temporal"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    yield
    shutil.rmtree(REPO / "solutions" / "day-99")
    if not any((REPO / "solutions").iterdir()):
        (REPO / "solutions").rmdir()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_solution_package_shadows_src(fake_solution):
    out = subprocess.run(
        [str(REPO / "scripts" / "solution.sh"), "99", "python", "-c",
         "import netops_temporal; print(netops_temporal.__file__)"],
        cwd="/", capture_output=True, text=True, check=True,
    ).stdout
    assert "solutions/day-99" in out


def test_solution_script_rejects_bad_day():
    result = subprocess.run(
        [str(REPO / "scripts" / "solution.sh"), "7", "python", "-V"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "two digits" in result.stderr
