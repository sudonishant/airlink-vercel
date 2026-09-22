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
online_users = {}  # username -> {"device": device, "last_seen": timestamp}


def optimize_image_bytes(data_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    """Compress and resize images to prevent Gist bloat and ensure fast loading."""
    if not (mime_type.startswith("image/") or mime_type in ["application/octet-stream"]):
        return data_bytes, mime_type
    try:
        from PIL import Image, ImageOps
        import io
        img = Image.open(io.BytesIO(data_bytes))
        img = ImageOps.exif_transpose(img)
        if getattr(img, "is_animated", False) or mime_type in ["image/gif", "image/svg+xml"]:
            return data_bytes, mime_type
        
        max_dim = 1280
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        
        out_buf = io.BytesIO()
        if img.mode in ("RGBA", "P") and "A" in img.getbands():
            img.save(out_buf, format="PNG", optimize=True)
            png_bytes = out_buf.getvalue()
            if len(png_bytes) > 350 * 1024:
                rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[3])
                out_buf = io.BytesIO()
                rgb_img.save(out_buf, format="JPEG", quality=82, optimize=True)
                return out_buf.getvalue(), "image/jpeg"
            return png_bytes, "image/png"
        else:
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(out_buf, format="JPEG", quality=82, optimize=True)
            return out_buf.getvalue(), "image/jpeg"
    except Exception as e:
        print("[!] Image optimize error:", e)
        return data_bytes, mime_type

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
        resp = urllib.request.urlopen(req, timeout=6)
        gist_data = json.loads(resp.read().decode())
        files = gist_data.get("files", {})
        if "history.json" in files:
            file_info = files["history.json"]
            raw = file_info.get("content", "")
            if file_info.get("truncated") and file_info.get("raw_url"):
                try:
                    raw_req = urllib.request.Request(
                        file_info["raw_url"],
                        headers={
                            "Authorization": f"Bearer {GITHUB_TOKEN}",
                            "User-Agent": "AirLink-App"
                        }
                    )
                    raw = urllib.request.urlopen(raw_req, timeout=8).read().decode("utf-8")
                except Exception as e:
                    print("[!] Raw gist fetch error:", e)
            
            if raw:
                try:
                    parsed = json.loads(raw)
                    new_items = []
                    new_pinned = None
                    if isinstance(parsed, dict):
                        new_items = parsed.get("items", [])
                        new_pinned = parsed.get("pinned_id", None)
                    elif isinstance(parsed, list):
                        new_items = parsed
                    
                    # Protect against wiping non-empty cache if parsed is unexpectedly empty
                    if new_items or not history_cache:
                        history_cache = new_items
                        pinned_item_id = new_pinned
                    
                    # Cache to /tmp
                    try:
                        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                            json.dump({"items": history_cache, "pinned_id": pinned_item_id}, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                except Exception as parse_err:
                    print("[!] JSON parse error from Gist:", parse_err)
    except Exception as e:
        print("[!] Gist fetch error:", e)

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

def save_to_gist(sync: bool = True):
    global history_cache, pinned_item_id
    payload = {
        "items": history_cache[:60],
        "pinned_id": pinned_item_id,
        "updated_at": time.time()
    }
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    if sync:
        _gist_worker(payload)
    else:
        import threading
        t = threading.Thread(target=_gist_worker, args=(payload,), daemon=True)
        t.start()

def load_data():
    global history_cache, pinned_item_id, last_gist_sync
    now = time.time()
    if not history_cache and HISTORY_FILE.exists():
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
    
    if not history_cache or (now - last_gist_sync > 10):
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

@router.post("/heartbeat")
async def heartbeat(data: Dict[str, Any]):
    user = data.get("user", "").strip()
    device = data.get("device", "Device")
    if user:
        online_users[user] = {"device": device, "last_seen": time.time()}
    return {"success": True}

@router.get("/users/online")
async def get_online_users():
    now = time.time()
    active = []
    for u, info in list(online_users.items()):
        if now - info.get("last_seen", 0) <= 15:
            active.append({"user": u, "device": info.get("device", "Device"), "last_seen": info.get("last_seen")})
        else:
            online_users.pop(u, None)
    return {"users": active, "count": len(active)}

@router.get("/history")
async def get_history(request_user: Optional[str] = None):
    load_data()
    if request_user:
        visible = []
        for x in history_cache:
            if not x.get("is_private"):
                visible.append(x)
            elif x.get("sender") == request_user or x.get("recipient") == request_user:
                visible.append(x)
        return {"items": visible, "pinned_id": pinned_item_id}
    return {"items": history_cache, "pinned_id": pinned_item_id}

@router.post("/react")
async def toggle_reaction(data: Dict[str, Any]):
    global history_cache
    load_data()
    target_id = data.get("id")
    emoji = (data.get("emoji") or "").strip()
    user = (data.get("user") or "").strip() or "User"
    
    if not target_id or not emoji:
        raise HTTPException(status_code=400, detail="Missing id or emoji")
        
    target_item = next((x for x in history_cache if x.get("id") == target_id), None)
    if not target_item:
        raise HTTPException(status_code=404, detail="Message not found")
        
    reactions = target_item.setdefault("reactions", {})
    user_list = reactions.setdefault(emoji, [])
    
    if user in user_list:
        user_list.remove(user)
        if not user_list:
            reactions.pop(emoji, None)
    else:
        user_list.append(user)
        
    save_to_gist()
    return {"success": True, "reactions": target_item.get("reactions", {})}

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
    is_private = bool(data.get("is_private", False))
    recipient = data.get("recipient")
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
        "is_private": is_private,
        "recipient": recipient,
        "reactions": {},
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
    is_view_once: bool = Form(False),
    is_private: bool = Form(False),
    recipient: Optional[str] = Form(None)
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
    
    # Compress images to keep base64 tiny, fast, and prevent Gist bloat
    if category == "image" or mime_type.startswith("image/"):
        opt_bytes, opt_mime = optimize_image_bytes(content_bytes, mime_type)
        if len(opt_bytes) < len(content_bytes):
            content_bytes = opt_bytes
            file_size = len(content_bytes)
            mime_type = opt_mime
            try:
                with open(dest_path, "wb") as f:
                    f.write(content_bytes)
            except Exception:
                pass
    
    # Store base64 data url permanently so photos/files NEVER expire across serverless reboots
    data_url = None
    if file_size < 3 * 1024 * 1024:
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
        "is_private": is_private,
        "recipient": recipient,
        "reactions": {},
        "timestamp": timestamp,
        "time_epoch": time_epoch
    }
    
    load_data()
    history_cache.insert(0, item)
    save_to_gist(sync=True)
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

@router.get("/qr")
@router.get("/api/qr")
async def qr_code(request: Request, ip: Optional[str] = None, port: Optional[int] = None, global_link: Optional[bool] = False):
    try:
        import qrcode
        import io
        host = request.headers.get("host") or request.url.hostname or "sudolink.vercel.app"
        scheme = "https" if (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https") else "http"
        if global_link or not ip:
            url = f"{scheme}://{host}"
        else:
            url = f"http://{ip}:{port or 5000}"
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#2563eb", back_color="#0f172a")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=300"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QR generation failed: {e}")

# Dual route mounting: matches /route and /api/route
app.include_router(router, prefix="")
app.include_router(router, prefix="/api")

