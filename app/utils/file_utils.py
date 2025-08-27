import os
import zipfile
import hashlib
from pathlib import Path
from fastapi import UploadFile



EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "env", "venv"}
EXCLUDE_FILE_EXTS = {".exe", ".dll", ".so", ".bin", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".tar", ".gz", ".rar", ".7z", ".pdf"}


def save_uploaded_file(upload_file: UploadFile, dest_path: str):
    """Save a single uploaded file to the destination path."""
    with open(dest_path, "wb") as f:
        f.write(upload_file.file.read())

def extract_zip_file(upload_file: UploadFile, dest_dir: str):
    """Extract a zip file to the destination directory."""
    upload_file.file.seek(0)
    with zipfile.ZipFile(upload_file.file) as zf:
        zf.extractall(dest_dir)

def handle_uploaded_files(files, dest_dir: str):
    """Process uploaded files: extract zips, save others."""
    os.makedirs(dest_dir, exist_ok=True)
    for file in files:
        if not file or not getattr(file, "filename", None) or file.filename.strip() == "":
            continue
        filename = file.filename
        if filename.lower().endswith('.zip'):
            extract_zip_file(file, dest_dir)
        else:
            dest_path = os.path.join(dest_dir, filename)
            save_uploaded_file(file, dest_path)

def get_project_files(project_id, get_project_source_path_func):
    """Return all file paths for a project, excluding certain files/folders."""
    src = get_project_source_path_func(project_id)
    if not src.exists():
        return []
    paths = []
    for p in src.rglob("*"):
        if p.is_file():
            parts = set(p.parts)
            if parts & EXCLUDE_DIRS:
                continue
            if p.suffix.lower() in EXCLUDE_FILE_EXTS:
                continue
            paths.append(p)
    return sorted(paths, key=lambda p: str(p).lower())

def read_text(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""