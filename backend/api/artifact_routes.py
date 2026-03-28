"""
Artifact serving routes — serves files from data/artifacts/{run_id}/.

Supports Range requests for media seeking (video/audio).
"""

import os
import mimetypes
import stat
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from services.artifact_service import get_artifact_path

router = APIRouter()


@router.get("/artifacts/{run_id}/{filename}")
async def serve_artifact(run_id: str, filename: str, request: Request):
    """Serve an artifact file with correct MIME type and optional Range support."""
    path = get_artifact_path(run_id, filename)
    if not path:
        return Response(status_code=404, content="Artifact not found")

    mime, _ = mimetypes.guess_type(filename)
    mime = mime or "application/octet-stream"

    # Check for Range header (needed for video/audio seeking)
    range_header = request.headers.get("range")
    if range_header:
        return _range_response(path, mime, range_header)

    # Inline display for media; attachment for everything else
    media_types = (
        "image/", "video/", "audio/", "application/pdf",
        "text/html", "text/plain",
    )
    disposition = "inline" if any(mime.startswith(t) for t in media_types) else "attachment"

    return FileResponse(
        path,
        media_type=mime,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


def _range_response(path: str, mime: str, range_header: str) -> Response:
    """Handle HTTP Range requests for media streaming."""
    file_size = os.stat(path)[stat.ST_SIZE]

    # Parse "bytes=start-end"
    try:
        range_spec = range_header.replace("bytes=", "").strip()
        parts = range_spec.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
    except (ValueError, IndexError):
        start = 0
        end = file_size - 1

    end = min(end, file_size - 1)
    length = end - start + 1

    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(length)

    return Response(
        content=data,
        status_code=206,
        media_type=mime,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )
