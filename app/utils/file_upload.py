import os
import uuid
from flask import current_app
from PIL import Image

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def save_image(file_storage, folder, max_px=600, max_bytes=2 * 1024 * 1024):
    """Validate (really an image), shrink and store. Returns the new filename.
    Raises ValueError with a user-friendly message."""
    name = (file_storage.filename or "").lower()
    if "." not in name or name.rsplit(".", 1)[1] not in IMAGE_EXTENSIONS:
        raise ValueError("Upload a PNG, JPG or WEBP image.")
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > max_bytes:
        raise ValueError(f"Image is too large. Maximum size is {max_bytes // (1024 * 1024)} MB.")
    try:
        img = Image.open(file_storage.stream)
        img.verify()
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)
    except Exception:
        raise ValueError("This file is not a valid image.")

    img.thumbnail((max_px, max_px))
    has_alpha = img.mode in ("RGBA", "LA", "P")
    target_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], folder)
    os.makedirs(target_dir, exist_ok=True)
    if has_alpha:
        filename, fmt, img = f"{uuid.uuid4().hex}.png", "PNG", img.convert("RGBA")
    else:
        filename, fmt, img = f"{uuid.uuid4().hex}.jpg", "JPEG", img.convert("RGB")
    img.save(os.path.join(target_dir, filename), fmt)
    return filename


def delete_upload(folder, filename):
    if not filename:
        return
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], folder, os.path.basename(filename))
    try:
        os.remove(path)
    except OSError:
        pass


DOC_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}


def save_document(file_storage, folder="documents", max_bytes=5 * 1024 * 1024):
    """Store a PDF/image exactly as uploaded (after checking it really is one).
    Returns (stored_name, original_name, size). Raises ValueError."""
    from werkzeug.utils import secure_filename
    original = secure_filename(file_storage.filename or "") or "document"
    ext = original.rsplit(".", 1)[1].lower() if "." in original else ""
    if ext not in DOC_EXTENSIONS:
        raise ValueError("Upload a PDF, PNG, JPG or WEBP file.")
    data = file_storage.read()
    if len(data) > max_bytes:
        raise ValueError(f"File is too large. Maximum size is {max_bytes // (1024 * 1024)} MB.")
    if not data:
        raise ValueError("The file is empty.")
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("This file is not a valid PDF.")
    else:
        import io
        try:
            Image.open(io.BytesIO(data)).verify()
        except Exception:
            raise ValueError("This file is not a valid image.")
    target_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], folder)
    os.makedirs(target_dir, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(target_dir, stored), "wb") as fh:
        fh.write(data)
    return stored, original, len(data)


ATTACHMENT_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt"}
INLINE_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}          # the browser may show these; the rest download


def save_attachment(file_storage, folder, max_bytes=10 * 1024 * 1024):
    """Store a teaching file (PDF, image, Word, PowerPoint, Excel, text) after checking its content really matches
    its extension. Returns (stored_name, original_name, size). Raises ValueError with a friendly message."""
    from werkzeug.utils import secure_filename
    original = secure_filename(file_storage.filename or "") or "file"
    ext = original.rsplit(".", 1)[1].lower() if "." in original else ""
    if ext not in ATTACHMENT_EXTENSIONS:
        raise ValueError("Upload a PDF, image, Word, PowerPoint, Excel or text file.")
    data = file_storage.read()
    if not data:
        raise ValueError("The file is empty.")
    if len(data) > max_bytes:
        raise ValueError(f"File is too large. Maximum size is {max_bytes // (1024 * 1024)} MB.")
    if ext == "pdf":
        ok = data.startswith(b"%PDF-")
    elif ext in ("docx", "pptx", "xlsx"):
        ok = data.startswith(b"PK\x03\x04")                       # Office Open XML files are zip archives
    elif ext in ("doc", "ppt", "xls"):
        ok = data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    elif ext == "txt":
        try:
            data.decode("utf-8")
            ok = b"\x00" not in data
        except UnicodeDecodeError:
            ok = False
    else:
        import io
        try:
            Image.open(io.BytesIO(data)).verify()
            ok = True
        except Exception:
            ok = False
    if not ok:
        raise ValueError(f"This file does not look like a real .{ext} file.")
    target_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], folder)
    os.makedirs(target_dir, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(target_dir, stored), "wb") as fh:
        fh.write(data)
    return stored, original, len(data)


def send_private(folder, filename, download_name=None, as_attachment=False):
    """Serve a private upload. Caller MUST have checked permission + branch first."""
    from flask import send_from_directory
    ext = os.path.basename(filename).rsplit(".", 1)[-1].lower()
    resp = send_from_directory(os.path.join(current_app.config["UPLOAD_FOLDER"], folder),
                               os.path.basename(filename), download_name=download_name,
                               as_attachment=as_attachment or ext not in INLINE_EXTENSIONS)
    resp.cache_control.public = False
    resp.cache_control.private = True
    resp.cache_control.max_age = 3600
    return resp
