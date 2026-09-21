#!/usr/bin/env python3
"""
AirLink v2.0 — Gist → Supabase Migration Script
================================================
Purane GitHub-Gist wale messages + files ko naye Supabase backend me shift karta hai.

Usage:
  1. Environment variables set karo (ya .env file banao):
       export SUPABASE_URL="https://xxxx.supabase.co"
       export SUPABASE_SERVICE_KEY="eyJ...service_role_key..."
  2. Pehle supabase_setup.sql run kar chuke ho (Supabase SQL Editor me)
  3. Dry-run (kuch write nahi hoga):
       python3 migrate_from_gist.py --dry-run
  4. Real migration:
       python3 migrate_from_gist.py

Options:
  --input FILE     backup JSON ka path (default: backup/gist_history_backup_*.json dhoondta hai)
  --raw URL        gist ka raw URL (agar backup file nahi hai to seedha gist se padho)
                   e.g. https://gist.githubusercontent.com/<user>/<id>/raw/history.json
"""

import argparse
import base64
import glob
import json
import mimetypes
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("❌ httpx install karo:  pip install httpx")

NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]{1,25}$")


def sanitize_name(name: str, fallback: str = "Unknown") -> str:
    n = re.sub(r"[^A-Za-z0-9 _.\-]", "", (name or "").strip())[:25].strip()
    return n or fallback


def sanitize_filename(name: str) -> str:
    safe = "".join(c for c in (name or "") if c.isalnum() or c in "._- ()")
    return safe or f"file_{int(time.time() * 1000)}"


def format_size(n) -> str:
    b = float(n or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{int(b)} B" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def load_source(args):
    if args.raw:
        print(f"⬇️  Fetching gist raw: {args.raw}")
        with urllib.request.urlopen(args.raw, timeout=30) as r:
            return json.loads(r.read().decode())
    if args.input:
        paths = [args.input]
    else:
        paths = sorted(glob.glob("backup/gist_history_backup_*.json")) or \
                sorted(glob.glob("../backup/gist_history_backup_*.json"))
    if not paths:
        sys.exit("❌ Koi backup JSON nahi mila. --input ya --raw use karo.")
    print(f"📂 Reading: {paths[-1]}")
    return json.loads(Path(paths[-1]).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="backup JSON file path")
    ap.add_argument("--raw", help="gist raw URL (direct fetch)")
    ap.add_argument("--dry-run", action="store_true", help="sirf dikhao, kuch write na ho")
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not args.dry_run and (not url or not key):
        sys.exit("❌ SUPABASE_URL / SUPABASE_SERVICE_KEY env vars set karo (dekho .env.example)")

    data = load_source(args)
    raw_items = data.get("items", []) if isinstance(data, dict) else data
    # purana format: naya message list me pehle — time_epoch se ascending me convert karo
    raw_items = sorted(raw_items, key=lambda x: x.get("time_epoch", 0))
    print(f"💬 {len(raw_items)} items mile\n")

    client = httpx.Client(timeout=120) if not args.dry_run else None
    hdrs = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    bucket = "airlink"
    stats = {"text": 0, "system": 0, "file": 0, "skipped": 0}

    for it in raw_items:
        typ = it.get("type", "text")
        epoch = it.get("time_epoch") or time.time()
        # ISO timestamp banao (purana format "YYYY-MM-DD HH:MM:SS" UTC tha)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch)) + "Z"
        sender = sanitize_name(it.get("sender"))
        recipient = sanitize_name(it.get("recipient")) if it.get("recipient") else None
        item_id = it.get("id") or f"mig_{int(epoch * 1000)}"

        if typ in ("text", "system"):
            row = {
                "id": item_id, "type": typ, "category": "system" if typ == "system" else "text",
                "content": it.get("content", ""), "sender": sender, "recipient": None,
                "is_private": False, "is_view_once": bool(it.get("is_view_once")),
                "is_consumed": bool(it.get("is_consumed")), "deleted": False,
                "reactions": it.get("reactions") or {},
                "created_at": ts, "time_epoch": epoch,
            }
            stats[typ] += 1
            if args.dry_run:
                preview = (row["content"] or "")[:60].replace("\n", " ")
                print(f"  [{typ}] {sender}: {preview}")
                continue
            r = client.post(f"{url}/rest/v1/messages", headers=hdrs, json=row)
            if r.status_code not in (200, 201):
                print(f"  ⚠️ insert fail ({r.status_code}): {r.text[:120]}")
            continue

        if typ == "file":
            vu = it.get("view_url") or ""
            b64 = vu.split(",", 1)[1] if vu.startswith("data:") else None
            if not b64:
                print(f"  ⚠️ skip (file data nahi): {it.get('filename')}")
                stats["skipped"] += 1
                continue
            raw = base64.b64decode(b64)
            mime = (vu.split(";", 1)[0].replace("data:", "") or
                    mimetypes.guess_type(it.get("filename", ""))[0] or "application/octet-stream")
            fname = sanitize_filename(it.get("filename") or it.get("original_name") or "file")
            path = f"migrated/{item_id}_{fname}"
            stats["file"] += 1
            if args.dry_run:
                print(f"  [file] {fname} ({format_size(len(raw))}) -> {path}")
                continue
            up = client.post(
                f"{url}/storage/v1/object/{bucket}/{urllib.parse.quote(path)}",
                headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": mime},
                content=raw)
            if up.status_code not in (200, 201):
                print(f"  ⚠️ upload fail ({up.status_code}): {up.text[:120]}")
                continue
            cat = it.get("category") or "other"
            row = {
                "id": item_id, "type": "file", "category": cat,
                "filename": fname, "original_name": it.get("original_name") or fname,
                "file_size": len(raw), "formatted_size": format_size(len(raw)),
                "mime_type": mime, "storage_path": path,
                "sender": sender, "recipient": recipient,
                "is_private": bool(it.get("is_private")),
                "is_view_once": bool(it.get("is_view_once")),
                "is_consumed": bool(it.get("is_consumed")), "deleted": False,
                "reactions": it.get("reactions") or {},
                "created_at": ts, "time_epoch": epoch,
            }
            r = client.post(f"{url}/rest/v1/messages", headers=hdrs, json=row)
            if r.status_code not in (200, 201):
                print(f"  ⚠️ insert fail ({r.status_code}): {r.text[:120]}")

    print(f"\n✅ Done! text={stats['text']} system={stats['system']} "
          f"file={stats['file']} skipped={stats['skipped']}"
          + (" (DRY RUN — kuch write nahi hua)" if args.dry_run else ""))
    if not args.dry_run:
        print("🎉 Ab naya app kholo — saare purane messages wahan dikhne chahiye!")


if __name__ == "__main__":
    main()
