"""Runs tests/system/dashboard_e2e.py (dashboard + API + database) in its own process."""
import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "system", "dashboard_e2e.py")


def _dashboard_deps_ok() -> bool:
    probe = "import numpy, pandas, pyarrow, plotly, streamlit; pyarrow.Table.from_pandas(pandas.DataFrame({'a': [1]}))"
    return subprocess.run([sys.executable, "-c", probe], capture_output=True).returncode == 0


@pytest.mark.skipif(not _dashboard_deps_ok(), reason="dashboard dependencies (requirements.txt) not installed")
def test_dashboard_end_to_end() -> None:
    proc = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, timeout=600)
    checks = "\n".join(line for line in proc.stdout.splitlines() if line.strip()[:1] in ("✓", "✗") or "FAILED" in line)
    assert proc.returncode == 0, f"{checks}\n{proc.stderr[-3000:]}"
    assert "All dashboard checks passed." in proc.stdout
