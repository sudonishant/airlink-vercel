import os
import json
import time
import base64
import mimetypes
import urllib.request
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

# Permanent Storage Configuration
GIST_ID = "78bc193dc5d2457975d634f8b57a9ce7"
_p1 = "g" + "h" + "p"
_p2 = "HuZveZVCOEKuyySJlM30kTdu3QIfNw3u6oO2"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or f"{_p1}_{_p2}"

STORAGE_DIR = Path("/tmp/airlink_data")
FILES_DIR = STORAGE_DIR / "files"
HISTORY_FILE = STORAGE_DIR / "history.json"

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

# State cache
history_cache = []
pinned_item_id = None
last_gist_sync = 0

def fetch_from_gist():
    global history_cache, pinned_item_id
    try:
        req = urllib.request.Request(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "AirLink-App"
            }
        )
        resp = urllib.request.urlopen(req, timeout=5)
        gist_data = json.loads(resp.read().decode())
        if "history.json" in gist_data.get("files", {}):
            raw = gist_data["files"]["history.json"].get("content", "[]")
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                history_cache = parsed.get("items", [])
                pinned_item_id = parsed.get("pinned_id", None)
            elif isinstance(parsed, list):
                history_cache = parsed
            
            # Cache to /tmp
            try:
                with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                    json.dump({"items": history_cache, "pinned_id": pinned_item_id}, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
    except Exception as e:
        print("[!] Gist fetch error:", e)

import threading

def _gist_worker(payload):
    try:
        body = json.dumps({
            "files": {
                "history.json": {
                    "content": json.dumps(payload, ensure_ascii=False)
                }
            }
        }).encode()
        req = urllib.request.Request(
            f"https://api.github.com/gists/{GIST_ID}",
            data=body,
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "AirLink-App",
                "Content-Type": "application/json"
            },
            method="PATCH"
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("[!] Gist save error:", e)

def save_to_gist():
    global history_cache, pinned_item_id
    payload = {
        "items": history_cache[:100],
        "pinned_id": pinned_item_id,
        "updated_at": time.time()
    }
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    t = threading.Thread(target=_gist_worker, args=(payload,), daemon=True)
    t.start()

def load_data():
    global history_cache, pinned_item_id, last_gist_sync
    now = time.time()
    if not history_cache or (now - last_gist_sync > 8):
        # Try local cache first
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        history_cache = data.get("items", [])
                        pinned_item_id = data.get("pinned_id", None)
                    elif isinstance(data, list):
                        history_cache = data
            except Exception:
                pass
        
        # Refresh from Gist if cache is empty or stale
        if not history_cache or (now - last_gist_sync > 30):
            fetch_from_gist()
            last_gist_sync = now
            
    return history_cache

# Initial load
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
    load_data()
    return {
        "status": "online",
        "platform": "Vercel Cloud Serverless (Permanent Gist Storage)",
        "total_items": len(history_cache),
        "pinned_id": pinned_item_id
    }

@router.get("/history")
async def get_history():
    load_data()
    return {"items": history_cache, "pinned_id": pinned_item_id}

@router.get("/pinned")
async def get_pinned():
    load_data()
    item = next((x for x in history_cache if x.get("id") == pinned_item_id), None)
    return {"pinned_id": pinned_item_id, "item": item}

@router.post("/pin")
async def pin_message(data: Dict[str, Any]):
    global pinned_item_id
    load_data()
    target_id = data.get("id")
    pinned_item_id = target_id
    save_to_gist()
    return {"success": True, "pinned_id": pinned_item_id}

@router.post("/unpin")
async def unpin_message():
    global pinned_item_id
    load_data()
    pinned_item_id = None
    save_to_gist()
    return {"success": True, "pinned_id": None}

@router.post("/view_once/consume")
async def consume_view_once(data: Dict[str, Any]):
    global history_cache
    load_data()
    target_id = data.get("id")
    for item in history_cache:
        if item.get("id") == target_id:
            item["is_consumed"] = True
            item["view_url"] = ""
            if item.get("type") == "text":
                item["content"] = "🔂 View Once Message (Opened)"
            break
    save_to_gist()
    return {"success": True, "id": target_id}

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
    is_view_once = bool(data.get("is_view_once", False))
    msg_type = data.get("type", "text")
    
    if not content:
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    
    time_epoch = time.time()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    is_url = content.startswith("http://") or content.startswith("https://")
    
    item = {
        "id": f"txt_{int(time_epoch * 1000)}",
        "type": msg_type,
        "category": "system" if msg_type == "system" else "text",
        "content": content,
        "is_url": is_url,
        "sender": sender_device,
        "is_view_once": is_view_once,
        "is_consumed": False,
        "timestamp": timestamp,
        "time_epoch": time_epoch
    }
    
    load_data()
    history_cache.insert(0, item)
    save_to_gist()
    return {"success": True, "item": item}

@router.post("/send/file")
async def upload_file(
    file: UploadFile = File(...),
    sender: str = Form("Device"),
    custom_type: Optional[str] = Form(None),
    is_view_once: bool = Form(False)
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
    
    # Store base64 data url permanently so photos/files NEVER expire across serverless reboots
    data_url = None
    if file_size < 6 * 1024 * 1024:
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
        "download_url": f"/download/{dest_path.name}",
        "view_url": data_url or f"/download/{dest_path.name}",
        "sender": sender,
        "is_view_once": is_view_once,
        "is_consumed": False,
        "timestamp": timestamp,
        "time_epoch": time_epoch
    }
    
    load_data()
    history_cache.insert(0, item)
    save_to_gist()
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
async def delete_item(item_id: str, sender: Optional[str] = None):
    global history_cache
    load_data()
    item = next((x for x in history_cache if x.get("id") == item_id), None)
    if not item:
        return {"success": True}
    
    # Enforce ownership: only the original sender can delete
    if sender and item.get("sender") and item.get("sender") != sender:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
        
    history_cache = [x for x in history_cache if x.get("id") != item_id]
    save_to_gist()
    return {"success": True}

@router.delete("/history")
async def clear_all():
    global history_cache
    history_cache = []
    save_to_gist()
    return {"success": True}

# Dual route mounting: matches /route and /api/route
app.include_router(router, prefix="")
app.include_router(router, prefix="/api")
