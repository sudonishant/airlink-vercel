import os
import json
import time
import base64
import mimetypes
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, APIRouter
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AirLink Vercel Cloud Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def fix_path(request: Request, call_next):
    path = request.scope.get("path", "")
    if "/index.py" in path:
        request.scope["path"] = path.replace("/index.py", "") or "/"
    return await call_next(request)

# /tmp is the writable storage directory on Vercel Serverless
STORAGE_DIR = Path("/tmp/airlink_data")
FILES_DIR = STORAGE_DIR / "files"
HISTORY_FILE = STORAGE_DIR / "history.json"

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

# In-memory storage cache
history_cache = []

def load_data():
    global history_cache
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history_cache = json.load(f)
        except Exception:
            history_cache = []
    return history_cache

def save_data():
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history_cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

load_data()

def format_size(bytes_size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}" if unit != 'B' else f"{bytes_size} B"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"

def categorize_file(filename: str, mime: str) -> str:
    ext = Path(filename).suffix.lower()
    if mime.startswith("image/") or ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp']:
        return "image"
    if mime.startswith("video/") or ext in ['.mp4', '.mkv', '.mov', '.avi', '.webm']:
        return "video"
    if mime.startswith("audio/") or ext in ['.mp3', '.wav', '.ogg', '.m4a', '.aac']:
        return "audio"
    if ext in ['.zip', '.tar', '.gz', '.bz2', '.7z', '.rar']:
        return "archive"
    if ext in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.apk']:
        return "document"
    return "other"

router = APIRouter()

@router.get("/info")
async def get_info():
    return {
        "status": "online",
        "platform": "Vercel Cloud Serverless",
        "total_items": len(history_cache)
    }

@router.get("/history")
async def get_history():
    load_data()
    return {"items": history_cache}

@router.get("/sync/pending")
async def get_pending_sync(since_epoch: float = 0.0):
    load_data()
    pending = [item for item in history_cache if item.get("time_epoch", 0) > since_epoch]
    return {
        "count": len(pending),
        "items": sorted(pending, key=lambda x: x.get("time_epoch", 0))
    }

@router.post("/send/text")
async def send_text(data: Dict[str, Any]):
    content = data.get("text", "").strip()
    sender_device = data.get("device", "Device")
    if not content:
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    
    time_epoch = time.time()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    is_url = content.startswith("http://") or content.startswith("https://")
    
    item = {
        "id": f"txt_{int(time_epoch * 1000)}",
        "type": "text",
        "category": "text",
        "content": content,
        "is_url": is_url,
        "sender": sender_device,
        "timestamp": timestamp,
        "time_epoch": time_epoch
    }
    
    load_data()
    history_cache.insert(0, item)
    save_data()
    return {"success": True, "item": item}

@router.post("/send/file")
async def upload_file(
    file: UploadFile = File(...),
    sender: str = Form("Device"),
    custom_type: Optional[str] = Form(None)
):
    original_name = file.filename or "file"
    time_epoch = time.time()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    
    safe_name = "".join(c for c in original_name if c.isalnum() or c in "._- ()")
    if not safe_name:
        safe_name = f"file_{int(time_epoch * 1000)}"
    
    dest_path = FILES_DIR / safe_name
    counter = 1
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    while dest_path.exists():
        dest_path = FILES_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
        
    content_bytes = await file.read()
    try:
        with open(dest_path, "wb") as f:
            f.write(content_bytes)
    except Exception:
        pass
        
    file_size = len(content_bytes)
    mime_type, _ = mimetypes.guess_type(str(dest_path))
    mime_type = mime_type or file.content_type or "application/octet-stream"
    
    category = custom_type or categorize_file(dest_path.name, mime_type)
    
    # Store base64 data url for images/audio under 4MB so they always preview and persist
    data_url = None
    if file_size < 4 * 1024 * 1024:
        b64 = base64.b64encode(content_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"
    
    item = {
        "id": f"file_{int(time_epoch * 1000)}",
        "type": "file",
        "category": category,
        "filename": dest_path.name,
        "original_name": original_name,
        "file_size": file_size,
        "formatted_size": format_size(file_size),
        "mime_type": mime_type,
        "download_url": f"/api/download/{dest_path.name}",
        "view_url": data_url or f"/api/download/{dest_path.name}",
        "sender": sender,
        "timestamp": timestamp,
        "time_epoch": time_epoch
    }
    
    load_data()
    history_cache.insert(0, item)
    save_data()
    return {"success": True, "item": item}

@router.get("/download/{filename}")
async def download_file(filename: str):
    file_path = FILES_DIR / filename
    load_data()
    if file_path.exists():
        with open(file_path, "rb") as f:
            data = f.read()
        mime, _ = mimetypes.guess_type(filename)
        return Response(content=data, media_type=mime or "application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    
    item = next((x for x in history_cache if x.get("filename") == filename), None)
    if item and item.get("view_url", "").startswith("data:"):
        header, encoded = item["view_url"].split(",", 1)
        raw = base64.b64decode(encoded)
        mime = header.split(";")[0].replace("data:", "")
        return Response(content=raw, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
        
    raise HTTPException(status_code=404, detail="File not found")

@router.delete("/history/{item_id}")
async def delete_item(item_id: str):
    global history_cache
    load_data()
    history_cache = [x for x in history_cache if x.get("id") != item_id]
    save_data()
    return {"success": True}

@router.delete("/history")
async def clear_all():
    global history_cache
    history_cache = []
    save_data()
    return {"success": True}

# Mount both with and without /api prefix
app.include_router(router, prefix="")
app.include_router(router, prefix="/api")
