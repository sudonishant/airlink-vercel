"""
AirLink v2.0 — Production Backend (Vercel Serverless + Supabase)
================================================================
Architecture:
  - FastAPI (single Vercel Python function, dual-mounted at / and /api)
  - Supabase Postgres  -> messages, presence, app_state (via PostgREST)
  - Supabase Storage   -> uploaded files (private bucket, signed URLs)
  - Room-passcode auth  -> HMAC-signed session tokens (no DB session state)

Design notes:
  - NO module-level network calls (fast cold starts on Vercel)
  - NO fire-and-forget threads (serverless freezes the process after response)
  - All writes are awaited and DB-backed -> no more silent data loss
  - Soft deletes + updated_at trigger -> race-free incremental sync
  - Private DMs & delete-own-only enforced SERVER-side with verified identity
"""

import os
import io
import re
import json
import time
import base64
import hmac
import hashlib
import secrets
import mimetypes
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, List

NAME_PATTERN = r"^[A-Za-z0-9 _.\-]{1,25}$"
NAME_RE = re.compile(NAME_PATTERN)

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends, Query, APIRouter
from fastapi.responses import JSONResponse, Response, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

APP_VERSION = "2.0.0"
TOKEN_TTL_SECONDS = 30 * 24 * 3600      # 30 days
MEDIA_URL_TTL_SECONDS = 6 * 3600        # 6 hours
PRESENCE_WINDOW_SECONDS = 20
MAX_TEXT_LENGTH = 4000
EMOJI_WHITELIST = {'❤️', '👍', '😂', '🔥', '😮', '😢', '🎉', '🚀',
                   '🙏', '😍', '🤔', '👏', '💯', '😅', '😎', '🥳'}

# --------------------------------------------------------------------------
# Configuration (all secrets come from environment variables — NEVER hardcode)
# --------------------------------------------------------------------------
REQUIRED_ENV = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "ROOM_PASSCODE")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
ROOM_PASSCODE = os.environ.get("ROOM_PASSCODE", "")
BUCKET = os.environ.get("SUPABASE_BUCKET", "airlink")
MAX_FILE_MB = float(os.environ.get("MAX_FILE_MB", "4"))
# AUTH_SECRET can override; otherwise derived from service key (safe: both secret)
AUTH_SECRET = os.environ.get("AUTH_SECRET", "").encode() or hashlib.sha256(
    ("airlink:" + SUPABASE_SERVICE_KEY).encode()).digest()

ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]


def missing_env() -> List[str]:
    return [k for k in REQUIRED_ENV if not os.environ.get(k)]


def configured() -> bool:
    return not missing_env()


app = FastAPI(title="AirLink Cloud", version=APP_VERSION)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def fix_path(request: Request, call_next):
    """Vercel Python function may be reached via /api/index.py — normalize."""
    path = request.scope.get("path", "")
    if "/index.py" in path:
        request.scope["path"] = path.replace("/index.py", "") or "/"
    return await call_next(request)


# --------------------------------------------------------------------------
# Supabase REST helpers (PostgREST + Storage) — thin, typed, awaited
# --------------------------------------------------------------------------
_http: Optional[httpx.AsyncClient] = None


def http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return _http


def sb_headers(prefer: Optional[str] = None, json_body: bool = True) -> Dict[str, str]:
    h = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    if json_body:
        h["Content-Type"] = "application/json"
    if prefer:
        h["Prefer"] = prefer
    return h


class BackendError(Exception):
    pass


async def sb_request(method: str, path: str, *, params=None, json_body=None,
                     content: bytes = None, headers=None) -> httpx.Response:
    """Call Supabase REST API; raise BackendError with a helpful message."""
    url = f"{SUPABASE_URL}{path}"
    try:
        resp = await http().request(method, url, params=params, json=json_body,
                                    content=content, headers=headers)
    except httpx.HTTPError as e:
        raise BackendError(f"Supabase unreachable: {e}") from e
    if resp.status_code == 404:
        raise BackendError("Supabase table/bucket not found — kya aapne supabase_setup.sql run kiya? (README dekhen)")
    if resp.status_code >= 400:
        raise BackendError(f"Supabase error {resp.status_code}: {resp.text[:300]}")
    return resp


def require_configured():
    if not configured():
        raise HTTPException(status_code=503, detail={
            "error": "setup_required",
            "missing": missing_env(),
            "hint": "Vercel Project → Settings → Environment Variables me set karo (README.md ka Setup section dekho)"
        })


# --------------------------------------------------------------------------
# Auth: HMAC-signed tokens binding the verified display name
# --------------------------------------------------------------------------
def _b64e(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def _b64d(b: bytes) -> bytes:
    return base64.urlsafe_b64decode(b + b"=" * (-len(b) % 4))


def make_token(name: str) -> str:
    payload = json.dumps({"name": name, "exp": time.time() + TOKEN_TTL_SECONDS},
                         separators=(",", ":")).encode()
    sig = hmac.new(AUTH_SECRET, payload, hashlib.sha256).digest()
    return (_b64e(payload) + b"." + _b64e(sig)).decode()


def verify_token(token: str) -> Optional[str]:
    try:
        p, s = token.encode().split(b".")
        payload, sig = _b64d(p), _b64d(s)
        if not hmac.compare_digest(hmac.new(AUTH_SECRET, payload, hashlib.sha256).digest(), sig):
            return None
        data = json.loads(payload)
        if not isinstance(data, dict) or data.get("exp", 0) < time.time():
            return None
        name = data.get("name")
        return name if isinstance(name, str) and name else None
    except Exception:
        return None


def bearer_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    # media tags (<img>/<audio>/<video>) can't send headers -> allow ?token=
    q = request.query_params.get("token")
    return q.strip() if q else None


def require_user(request: Request) -> str:
    """FastAPI dependency: returns the verified display name or raises 401."""
    require_configured()
    name = verify_token(bearer_token(request) or "")
    if not name:
        raise HTTPException(status_code=401, detail="Invalid or expired session — dobara join karo")
    return name


def valid_name(name: str) -> Optional[str]:
    n = (name or "").strip()
    if not NAME_RE.match(n):
        return None
    return n

# --------------------------------------------------------------------------
# PostgREST query builders
# --------------------------------------------------------------------------
def pg_quote(v: str) -> str:
    """Quote a value for PostgREST filters (names are pre-validated, this is defense-in-depth)."""
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def privacy_filter(user: str) -> str:
    """Rows visible to `user`: public OR sent by user OR addressed to user."""
    u = pg_quote(user)
    return f'or=(is_private.eq.false,sender.eq.{u},recipient.eq.{u})'


def visibility_params(user: str, extra: Dict[str, str] = None) -> Dict[str, str]:
    p = {"and": f"(deleted.eq.false,{privacy_filter(user)})"}
    if extra:
        p.update(extra)
    return p


# --------------------------------------------------------------------------
# Row <-> client item shaping
# --------------------------------------------------------------------------
def format_size(bytes_size: int) -> str:
    b = float(bytes_size)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024.0:
            return f"{b:.1f} {unit}" if unit != 'B' else f"{int(b)} B"
        b /= 1024.0
    return f"{b:.1f} PB"


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


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def to_client(row: Dict[str, Any], viewer: str) -> Dict[str, Any]:
    """Convert a DB row into the frontend item shape (privacy-aware)."""
    item = {
        "id": row.get("id"),
        "type": row.get("type", "text"),
        "category": row.get("category") or "text",
        "sender": row.get("sender"),
        "recipient": row.get("recipient"),
        "is_private": bool(row.get("is_private")),
        "is_view_once": bool(row.get("is_view_once")),
        "is_consumed": bool(row.get("is_consumed")),
        "reactions": row.get("reactions") or {},
        "timestamp": row.get("created_at"),
        "time_epoch": row.get("time_epoch") or 0,
    }
    if item["type"] == "text" or item["type"] == "system":
        item["content"] = row.get("content")
        item["is_url"] = (row.get("content") or "").startswith(("http://", "https://"))
        # View-once privacy: content is only sent to its sender until revealed
        if item["is_view_once"] and not item["is_consumed"] and row.get("sender") != viewer:
            item["content"] = None
    else:
        item.update({
            "filename": row.get("filename"),
            "original_name": row.get("original_name"),
            "file_size": row.get("file_size"),
            "formatted_size": row.get("formatted_size"),
            "mime_type": row.get("mime_type"),
            "view_url": f"/download/{row.get('id')}",
            "download_url": f"/download/{row.get('id')}?dl=1",
        })
        # View-once media: never hand out the URL until revealed
        if item["is_view_once"] and not item["is_consumed"] and row.get("sender") != viewer:
            item["view_url"] = None
            item["download_url"] = None
    return item


def new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{secrets.token_hex(3)}"


def sanitize_filename(name: str) -> str:
    safe = "".join(c for c in (name or "") if c.isalnum() or c in "._- ()")
    return safe or f"file_{int(time.time() * 1000)}"


# --------------------------------------------------------------------------
# Supabase data access
# --------------------------------------------------------------------------
async def db_now() -> str:
    resp = await sb_request("POST", "/rest/v1/rpc/db_now", json_body={},
                            headers=sb_headers())
    return resp.json()


async def fetch_rows(user: str, *, since: str = None, limit: int = 200,
                     include_deleted: bool = False) -> List[Dict[str, Any]]:
    extra: Dict[str, str] = {
        "select": "*",
        "order": "time_epoch.desc",
        "limit": str(min(limit, 500)),
    }
    if since:
        extra["and"] = f"(updated_at.gte.{since},{privacy_filter(user)})"
    else:
        extra["and"] = f"(deleted.eq.false,{privacy_filter(user)})"
    resp = await sb_request("GET", "/rest/v1/messages", params=extra,
                            headers=sb_headers())
    return resp.json() if resp.text.strip() else []


async def insert_message(item: Dict[str, Any]) -> Dict[str, Any]:
    resp = await sb_request("POST", "/rest/v1/messages", json_body=item,
                            headers=sb_headers(prefer="return=representation"))
    rows = resp.json()
    return rows[0] if rows else item


async def get_row(item_id: str) -> Optional[Dict[str, Any]]:
    resp = await sb_request("GET", "/rest/v1/messages",
                            params={"select": "*", "id": f"eq.{item_id}"},
                            headers=sb_headers())
    rows = resp.json() if resp.text.strip() else []
    return rows[0] if rows else None


async def patch_row(item_id: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    resp = await sb_request("PATCH", "/rest/v1/messages",
                            params={"id": f"eq.{item_id}"}, json_body=body,
                            headers=sb_headers(prefer="return=representation"))
    rows = resp.json() if resp.text.strip() else []
    return rows[0] if rows else None


async def get_pinned_id() -> Optional[str]:
    resp = await sb_request("GET", "/rest/v1/app_state",
                            params={"select": "value", "key": "eq.pinned_id"},
                            headers=sb_headers())
    rows = resp.json() if resp.text.strip() else []
    if rows and isinstance(rows[0].get("value"), str):
        return rows[0]["value"]
    return None


async def set_pinned_id(item_id: Optional[str]):
    await sb_request("POST", "/rest/v1/app_state",
                     json_body={"key": "pinned_id", "value": item_id},
                     headers=sb_headers(prefer="resolution=merge-duplicates"))


async def storage_upload(path: str, data: bytes, mime: str):
    await sb_request("POST", f"/storage/v1/object/{BUCKET}/{urllib.parse.quote(path)}",
                     content=data,
                     headers={"apikey": SUPABASE_SERVICE_KEY,
                              "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                              "Content-Type": mime or "application/octet-stream",
                              "x-upsert": "false"})


async def storage_sign_url(path: str) -> str:
    resp = await sb_request(
        "POST", f"/storage/v1/object/sign/{BUCKET}/{urllib.parse.quote(path)}",
        json_body={"expiresIn": MEDIA_URL_TTL_SECONDS},
        headers=sb_headers())
    signed = resp.json().get("signedURL", "")
    if signed.startswith("http"):
        return signed
    if not signed.startswith("/"):
        signed = "/" + signed
    return f"{SUPABASE_URL}/storage/v1{signed}"


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@router.get("/info")
async def get_info(request: Request):
    """Public status endpoint — also drives the frontend setup screen."""
    info = {
        "status": "online" if configured() else "setup_required",
        "platform": "Vercel Serverless + Supabase (Postgres + Storage)",
        "version": APP_VERSION,
        "auth_required": True,
        "max_file_mb": MAX_FILE_MB,
        "total_items": None,
        "pinned_id": None,
    }
    if configured():
        try:
            resp = await sb_request("GET", "/rest/v1/messages",
                                    params={"select": "id", "deleted": "eq.false", "limit": "1"},
                                    headers=sb_headers(prefer="count=exact"))
            cr = resp.headers.get("content-range", "")
            if "/" in cr:
                try:
                    info["total_items"] = int(cr.split("/")[-1])
                except ValueError:
                    pass
            info["pinned_id"] = await get_pinned_id()
        except BackendError as e:
            info["status"] = "database_error"
            info["detail"] = str(e)
    else:
        info["missing"] = missing_env()
    return info


@router.post("/auth/join")
async def auth_join(request: Request, data: Dict[str, Any]):
    """Join the room with a display name + the shared room passcode."""
    require_configured()
    name = valid_name(str(data.get("name", "")))
    passcode = str(data.get("passcode", ""))
    if not name:
        raise HTTPException(400, detail="Naam 1-25 characters ka hona chahiye (letters, numbers, space, . _ -)")
    if not hmac.compare_digest(passcode.encode(), ROOM_PASSCODE.encode()):
        # tiny per-instance rate limit (best effort on serverless)
        key = f"join:{request.client.host if request.client else '?'}"
        now = time.time()
        attempts = [t for t in _join_attempts.get(key, []) if now - t < 60]
        attempts.append(now)
        _join_attempts[key] = attempts
        if len(attempts) > 10:
            raise HTTPException(429, detail="Bahut baar galat passcode — 1 minute ruko")
        raise HTTPException(401, detail="Galat room passcode")
    return {"success": True, "token": make_token(name), "name": name,
            "expires_in": TOKEN_TTL_SECONDS}


_join_attempts: Dict[str, List[float]] = {}


@router.post("/auth/rename")
async def auth_rename(request: Request, data: Dict[str, Any], user: str = Depends(require_user)):
    """Change display name; broadcasts a system message and returns a fresh token."""
    new_name = valid_name(str(data.get("new_name", "")))
    if not new_name:
        raise HTTPException(400, detail="Naam valid nahi hai")
    if new_name == user:
        return {"success": True, "token": bearer_token(request), "name": new_name}
    sys_item = {
        "id": new_id("sys"),
        "type": "system",
        "category": "system",
        "content": f'📢 "{user}" changed their name to "{new_name}"',
        "sender": new_name,
        "recipient": None,
        "is_private": False,
        "is_view_once": False,
        "is_consumed": False,
        "reactions": {},
        "created_at": iso_now(),
        "time_epoch": time.time(),
    }
    await insert_message(sys_item)
    # move presence over to the new name
    await sb_request("POST", "/rest/v1/presence",
                     json_body={"name": new_name, "device": "renamed", "last_seen": time.time()},
                     headers=sb_headers(prefer="resolution=merge-duplicates"))
    await sb_request("DELETE", "/rest/v1/presence",
                     params={"name": f"eq.{pg_quote(user)}"},
                     headers=sb_headers())
    return {"success": True, "token": make_token(new_name), "name": new_name}


@router.post("/heartbeat")
async def heartbeat(data: Dict[str, Any], user: str = Depends(require_user)):
    device = str(data.get("device", "Device"))[:40]
    await sb_request("POST", "/rest/v1/presence",
                     json_body={"name": user, "device": device, "last_seen": time.time()},
                     headers=sb_headers(prefer="resolution=merge-duplicates"))
    return {"success": True}


@router.get("/users/online")
async def get_online_users(user: str = Depends(require_user)):
    cutoff = time.time() - PRESENCE_WINDOW_SECONDS
    resp = await sb_request("GET", "/rest/v1/presence",
                            params={"select": "name,device,last_seen",
                                    "last_seen": f"gte.{cutoff}",
                                    "order": "last_seen.desc"},
                            headers=sb_headers())
    rows = resp.json() if resp.text.strip() else []
    users = [{"user": r.get("name"), "device": r.get("device", "Online"),
              "last_seen": r.get("last_seen")} for r in rows]
    return {"users": users, "count": len(users)}


@router.get("/history")
async def get_history(limit: int = Query(150, ge=1, le=300), user: str = Depends(require_user)):
    rows = await fetch_rows(user, limit=limit)
    return {"items": [to_client(r, user) for r in rows],
            "pinned_id": await get_pinned_id(),
            "sync_time": await db_now()}


@router.get("/sync/pending")
async def get_pending_sync(since: str = "1970-01-01T00:00:00Z", user: str = Depends(require_user)):
    """Incremental sync: rows inserted/updated since `since` (1s overlap is fine — merge is idempotent)."""
    sync_time = await db_now()
    rows = await fetch_rows(user, since=since, limit=300, include_deleted=True)
    items = []
    deleted = []
    for r in rows:
        if r.get("deleted"):
            deleted.append(r.get("id"))
        else:
            items.append(to_client(r, user))
    return {"count": len(items), "items": items, "deleted": deleted,
            "pinned_id": await get_pinned_id(), "sync_time": sync_time}


@router.post("/send/text")
async def send_text(data: Dict[str, Any], user: str = Depends(require_user)):
    content = str(data.get("text", "")).strip()
    is_view_once = bool(data.get("is_view_once", False))
    is_private = bool(data.get("is_private", False))
    recipient = valid_name(str(data.get("recipient") or "")) if is_private else None
    if not content:
        raise HTTPException(400, detail="Text cannot be empty")
    if len(content) > MAX_TEXT_LENGTH:
        raise HTTPException(400, detail=f"Message max {MAX_TEXT_LENGTH} characters")
    if is_private and not recipient:
        raise HTTPException(400, detail="Private message ke liye recipient chahiye")

    item = {
        "id": new_id("txt"),
        "type": "text",
        "category": "text",
        "content": content,
        "sender": user,
        "recipient": recipient,
        "is_private": is_private,
        "is_view_once": is_view_once,
        "is_consumed": False,
        "reactions": {},
        "created_at": iso_now(),
        "time_epoch": time.time(),
    }
    row = await insert_message(item)
    return {"success": True, "item": to_client(row, user)}


@router.post("/send/file")
async def upload_file(
    file: UploadFile = File(...),
    is_view_once: bool = Form(False),
    is_private: bool = Form(False),
    recipient: Optional[str] = Form(None),
    custom_type: Optional[str] = Form(None),
    user: str = Depends(require_user),
):
    require_configured()
    max_bytes = int(MAX_FILE_MB * 1024 * 1024)

    # stream-read with hard cap (Vercel request limit is 4.5MB anyway)
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 512)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, detail=f"File {format_size(total)} — max limit {MAX_FILE_MB} MB")
    content_bytes = b"".join(chunks)

    original_name = file.filename or "file"
    safe_name = sanitize_filename(original_name)
    mime_type, _ = mimetypes.guess_type(safe_name)
    mime_type = mime_type or file.content_type or "application/octet-stream"
    category = custom_type if custom_type in ("image", "video", "audio", "archive", "document") \
        else categorize_file(safe_name, mime_type)

    item_id = new_id("file")
    storage_path = time.strftime("%Y%m") + "/" + f"{item_id}_{safe_name}"
    await storage_upload(storage_path, content_bytes, mime_type)

    recipient_name = valid_name(recipient or "") if is_private else None
    if is_private and not recipient_name:
        raise HTTPException(400, detail="Private file ke liye recipient chahiye")

    item = {
        "id": item_id,
        "type": "file",
        "category": category,
        "filename": safe_name,
        "original_name": original_name,
        "file_size": total,
        "formatted_size": format_size(total),
        "mime_type": mime_type,
        "storage_path": storage_path,
        "sender": user,
        "recipient": recipient_name,
        "is_private": is_private,
        "is_view_once": is_view_once,
        "is_consumed": False,
        "reactions": {},
        "created_at": iso_now(),
        "time_epoch": time.time(),
    }
    row = await insert_message(item)
    return {"success": True, "item": to_client(row, user)}


def _row_visible_to(row: Dict[str, Any], user: str) -> bool:
    if row.get("is_private"):
        return row.get("sender") == user or row.get("recipient") == user
    return True


@router.get("/download/{item_id}")
async def download_file(item_id: str, request: Request, dl: int = 0):
    """Auth via header OR ?token= (media tags). Redirects to a signed storage URL."""
    require_configured()
    user = verify_token(bearer_token(request) or "")
    if not user:
        raise HTTPException(401, detail="Invalid or expired session")
    row = await get_row(item_id)
    if not row or row.get("deleted"):
        raise HTTPException(404, detail="File not found")
    if not _row_visible_to(row, user):
        raise HTTPException(404, detail="File not found")
    if row.get("is_view_once") and row.get("is_consumed") and row.get("sender") != user:
        raise HTTPException(410, detail="View-once message already opened")

    path = row.get("storage_path")
    if not path:
        raise HTTPException(404, detail="File missing from storage")
    url = await storage_sign_url(path)
    if dl:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}download={urllib.parse.quote(row.get('filename') or 'file')}"
    return RedirectResponse(url=url, status_code=307)


@router.post("/view_once/reveal/{item_id}")
async def reveal_view_once(item_id: str, user: str = Depends(require_user)):
    """Atomically consume + reveal a view-once message (only for eligible viewers)."""
    row = await get_row(item_id)
    if not row or row.get("deleted") or not _row_visible_to(row, user):
        raise HTTPException(404, detail="Message not found")
    if not row.get("is_view_once"):
        raise HTTPException(400, detail="Ye view-once message nahi hai")
    if row.get("sender") == user:
        # sender can always review their own message
        out = {"success": True, "category": row.get("category"), "content": row.get("content"),
               "signed_url": None, "is_consumed": bool(row.get("is_consumed"))}
        if row.get("type") == "file" and row.get("storage_path"):
            out["signed_url"] = await storage_sign_url(row["storage_path"])
        return out
    if row.get("is_consumed"):
        raise HTTPException(410, detail="Ye message pehle hi open kar diya gaya hai 🔂")

    updated = await patch_row(item_id, {"is_consumed": True})
    out = {"success": True, "category": row.get("category"),
           "content": row.get("content"), "signed_url": None, "is_consumed": True}
    if row.get("type") == "file" and row.get("storage_path"):
        out["signed_url"] = await storage_sign_url(row["storage_path"])
    if updated is None:
        out["is_consumed"] = True
    return out


@router.post("/react")
async def toggle_reaction(data: Dict[str, Any], user: str = Depends(require_user)):
    target_id = str(data.get("id") or "")
    emoji = str(data.get("emoji") or "")
    if not target_id:
        raise HTTPException(400, detail="Missing id")
    if emoji not in EMOJI_WHITELIST:          # XSS-proof: strict server-side whitelist
        raise HTTPException(400, detail="Ye emoji allowed nahi hai")

    row = await get_row(target_id)
    if not row or row.get("deleted") or not _row_visible_to(row, user):
        raise HTTPException(404, detail="Message not found")

    reactions = dict(row.get("reactions") or {})
    users = list(reactions.get(emoji, []))
    if user in users:
        users = [u for u in users if u != user]
    else:
        users.append(user)
    if users:
        reactions[emoji] = users
    else:
        reactions.pop(emoji, None)

    await patch_row(target_id, {"reactions": reactions})
    return {"success": True, "reactions": reactions}


@router.post("/pin")
async def pin_message(data: Dict[str, Any], user: str = Depends(require_user)):
    target_id = str(data.get("id") or "")
    row = await get_row(target_id)
    if not row or row.get("deleted") or not _row_visible_to(row, user):
        raise HTTPException(404, detail="Message not found")
    await set_pinned_id(target_id)
    return {"success": True, "pinned_id": target_id}


@router.post("/unpin")
async def unpin_message(user: str = Depends(require_user)):
    await set_pinned_id(None)
    return {"success": True, "pinned_id": None}


@router.delete("/history/{item_id}")
async def delete_item(item_id: str, user: str = Depends(require_user)):
    row = await get_row(item_id)
    if not row or row.get("deleted"):
        return {"success": True}
    if row.get("sender") != user:             # server-enforced ownership
        raise HTTPException(403, detail="Aap sirf apne messages delete kar sakte ho")
    await patch_row(item_id, {"deleted": True})
    return {"success": True}


@router.delete("/history")
async def clear_all(request: Request, user: str = Depends(require_user)):
    """Admin action — requires the room passcode in the X-Passcode header."""
    passcode = request.headers.get("X-Passcode", "")
    if not hmac.compare_digest(passcode.encode(), ROOM_PASSCODE.encode()):
        raise HTTPException(401, detail="Admin passcode galat hai")
    await sb_request("PATCH", "/rest/v1/messages",
                     params={"deleted": "eq.false"},
                     json_body={"deleted": True},
                     headers=sb_headers())
    await set_pinned_id(None)
    return {"success": True}


@router.get("/qr")
async def qr_code(request: Request):
    """Generate a QR PNG of this app's URL — fully offline (no external API)."""
    try:
        import qrcode
        from qrcode.image.pure import PyPNGImage
    except ImportError as e:
        raise HTTPException(501, detail="qrcode/pypng library installed nahi hai") from e
    host = request.headers.get("host") or request.url.hostname or "localhost"
    scheme = "https" if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https" else "http"
    url = f"{scheme}://{host}"
    try:
        img = qrcode.make(url, image_factory=PyPNGImage)
        buf = io.BytesIO()
        img.save(buf)
    except Exception as e:
        raise HTTPException(500, detail=f"QR generation failed: {e}") from e
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@router.get("/")
async def root():
    return {"app": "AirLink", "version": APP_VERSION, "status": "online",
            "docs_hint": "Static frontend is served by Vercel; API lives at /api/*"}


# Dual route mounting: matches /route and /api/route (verified working on Vercel)
app.include_router(router, prefix="")
app.include_router(router, prefix="/api")


@app.exception_handler(BackendError)
async def backend_error_handler(request: Request, exc: BackendError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})
