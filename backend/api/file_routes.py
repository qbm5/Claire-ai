import os
import aiofiles
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse
from config import UPLOADS_DIR

router = APIRouter()


@router.post("/upload/{target_id}")
async def upload_files(target_id: str, files: list[UploadFile] = File(...)):
    upload_dir = os.path.join(UPLOADS_DIR, target_id)
    os.makedirs(upload_dir, exist_ok=True)
    saved = []
    for file in files:
        dest = os.path.join(upload_dir, file.filename)
        async with aiofiles.open(dest, "wb") as f:
            content = await file.read()
            await f.write(content)
        saved.append(file.filename)
    return {"response": "ok", "files": saved}


@router.get("/uploads/{target_id}")
async def list_uploads(target_id: str):
    upload_dir = os.path.join(UPLOADS_DIR, target_id)
    if not os.path.isdir(upload_dir):
        return []
    files = []
    for fname in sorted(os.listdir(upload_dir)):
        fpath = os.path.join(upload_dir, fname)
        if os.path.isfile(fpath):
            files.append({"name": fname, "size": os.path.getsize(fpath)})
    return files


@router.delete("/uploads/{target_id}/{filename}")
async def delete_upload(target_id: str, filename: str):
    fpath = os.path.join(UPLOADS_DIR, target_id, filename)
    if os.path.isfile(fpath):
        os.remove(fpath)
        return {"response": "ok"}
    return {"error": "file not found"}


@router.get("/download/{path:path}")
async def download_file(path: str):
    full_path = os.path.join(UPLOADS_DIR, path)
    if os.path.isfile(full_path):
        return FileResponse(full_path)
    return {"error": "file not found"}
