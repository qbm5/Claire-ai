"""Azure Blob Storage helpers for tool image upload."""

import io
import uuid
from urllib.parse import urlparse

from config import AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER

_cached_container_client = None


def _get_container_client():
    global _cached_container_client
    if _cached_container_client is not None:
        return _cached_container_client

    from azure.storage.blob import BlobServiceClient, PublicAccess

    if not AZURE_STORAGE_CONNECTION_STRING:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is not configured")

    service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    container = service.get_container_client(AZURE_STORAGE_CONTAINER)

    # Create container if it doesn't exist (public blob read)
    try:
        container.get_container_properties()
    except Exception:
        container = service.create_container(AZURE_STORAGE_CONTAINER, public_access=PublicAccess.BLOB)

    _cached_container_client = container
    return container


def resize_and_upload(file_bytes: bytes, filename: str) -> str:
    """Resize image to 200x200 and upload to Azure Blob Storage. Returns the blob URL."""
    from PIL import Image

    img = Image.open(io.BytesIO(file_bytes))
    img = img.convert("RGBA") if img.mode == "RGBA" else img.convert("RGB")
    img = img.resize((200, 200), Image.LANCZOS)

    buf = io.BytesIO()
    fmt = "PNG" if img.mode == "RGBA" else "JPEG"
    ext = "png" if fmt == "PNG" else "jpg"
    img.save(buf, format=fmt, quality=90)
    buf.seek(0)

    blob_name = f"{uuid.uuid4().hex}.{ext}"
    content_type = f"image/{ext}" if ext == "png" else "image/jpeg"

    container = _get_container_client()
    from azure.storage.blob import ContentSettings
    container.upload_blob(
        blob_name,
        buf,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )

    return f"{container.url}/{blob_name}"


def delete_blob(blob_url: str) -> None:
    """Delete a blob given its full URL."""
    if not blob_url:
        return

    parsed = urlparse(blob_url)
    # Path is like /container-name/blob-name
    parts = parsed.path.lstrip("/").split("/", 1)
    if len(parts) < 2:
        return
    blob_name = parts[1]

    container = _get_container_client()
    try:
        container.delete_blob(blob_name)
    except Exception:
        pass  # Blob may already be deleted
