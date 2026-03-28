"""Shared pip install utilities used by tool_routes and trigger_routes."""

import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as get_version


def is_package_installed(pkg_spec: str) -> bool:
    """Check if a pip package is already installed."""
    match = re.match(r'^([A-Za-z0-9_.-]+)', pkg_spec)
    if not match:
        return False
    try:
        get_version(match.group(1))
        return True
    except PackageNotFoundError:
        return False


def install_packages(packages: list[str]) -> list[dict]:
    """Install pip packages, skipping already-installed ones.

    Returns a list of result dicts for packages that were actually installed
    (or failed). Already-installed packages are silently skipped.
    """
    pip_results = []
    for pkg in packages:
        pkg = pkg.strip()
        if not pkg:
            continue
        if is_package_installed(pkg):
            continue
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg],
                capture_output=True, text=True, timeout=120,
            )
            pip_results.append({
                "package": pkg,
                "success": proc.returncode == 0,
                "output": proc.stdout.strip(),
                "error": proc.stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            pip_results.append({"package": pkg, "success": False, "output": "", "error": "Install timed out"})
        except Exception as e:
            pip_results.append({"package": pkg, "success": False, "output": "", "error": str(e)})
    return pip_results
