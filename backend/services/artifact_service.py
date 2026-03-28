"""
Artifact service — manages files and links produced by agent tools during pipeline runs.

Provides:
  - `save_artifact(filepath)` — register a file, returns a serve URL
  - `save_link(url, title)` — register an external link for prominent display
  - `collect_artifacts()` — gather all registered artifacts for the pipeline engine

Files are copied to data/artifacts/{run_id}/ and served via /api/artifacts/.

Uses contextvars so state propagates correctly through asyncio.to_thread().
"""

import os
import shutil
import contextvars
import mimetypes
from typing import Optional

from config import ARTIFACTS_DIR

# Context variables — propagated by asyncio.to_thread automatically
_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("artifact_run_id", default="")
_artifacts_var: contextvars.ContextVar[list] = contextvars.ContextVar("artifact_list")


def init_artifact_context(run_id: str):
    """Initialize artifact tracking for a run/step execution."""
    _run_id_var.set(run_id)
    _artifacts_var.set([])


def collect_artifacts() -> list[dict]:
    """Collect and return all artifacts registered during this context, then clear."""
    try:
        artifacts = list(_artifacts_var.get())
    except LookupError:
        return []
    _artifacts_var.set([])
    return artifacts


def save_artifact(filepath: str, name: Optional[str] = None) -> str:
    """Copy a file into the artifact store and return its serve URL.

    This is the function injected into agent function globals.

    Args:
        filepath: Path to the source file on disk.
        name: Optional display/serve name. Defaults to the file's basename.

    Returns:
        URL string like "/api/artifacts/{run_id}/{filename}" that can be
        embedded in markdown or returned as tool output.
    """
    run_id = _run_id_var.get()
    if not run_id:
        run_id = "_tool_test"

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"save_artifact: file not found: {filepath}")

    basename = name or os.path.basename(filepath)
    # Sanitize filename
    safe_name = "".join(
        c if c.isalnum() or c in (".", "-", "_", " ") else "_"
        for c in basename
    ).strip() or "artifact"

    dest_dir = os.path.join(ARTIFACTS_DIR, run_id)
    os.makedirs(dest_dir, exist_ok=True)

    dest_path = os.path.join(dest_dir, safe_name)

    # Deduplicate if name collision
    if os.path.exists(dest_path):
        root, ext = os.path.splitext(safe_name)
        counter = 1
        while os.path.exists(dest_path):
            safe_name = f"{root}_{counter}{ext}"
            dest_path = os.path.join(dest_dir, safe_name)
            counter += 1

    # Copy (or skip if same file)
    src_abs = os.path.normcase(os.path.abspath(filepath))
    dst_abs = os.path.normcase(os.path.abspath(dest_path))
    if src_abs != dst_abs:
        shutil.copy2(filepath, dest_path)

    size = os.path.getsize(dest_path)
    mime, _ = mimetypes.guess_type(safe_name)
    url = f"/api/artifacts/{run_id}/{safe_name}"

    artifact = {
        "type": "file",
        "filename": safe_name,
        "url": url,
        "mime": mime or "application/octet-stream",
        "size": size,
    }
    try:
        _artifacts_var.get().append(artifact)
    except LookupError:
        _artifacts_var.set([artifact])

    return url


def save_link(url: str, title: Optional[str] = None, description: Optional[str] = None) -> str:
    """Register an external link as an artifact for prominent display.

    This is the function injected into agent function globals.

    Args:
        url: The external URL (e.g. https://github.com/org/repo/pull/42).
        title: Optional short title for the link card.
        description: Optional description shown below the title.

    Returns:
        The same URL (pass-through for convenience).
    """
    artifact = {
        "type": "link",
        "url": url,
        "title": title or url,
    }
    if description:
        artifact["description"] = description
    try:
        _artifacts_var.get().append(artifact)
    except LookupError:
        _artifacts_var.set([artifact])

    return url


def get_artifact_path(run_id: str, filename: str) -> Optional[str]:
    """Resolve an artifact to its filesystem path, or None if not found."""
    path = os.path.join(ARTIFACTS_DIR, run_id, filename)
    if os.path.isfile(path):
        return path
    return None
