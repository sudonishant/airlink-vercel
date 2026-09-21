# Changelog

## v2.0.0 — Production Rebuild (2026-09-21)

### 🔥 Breaking (architecture)
- **Storage engine badla:** GitHub Gist → **Supabase** (Postgres + Storage)
  - Purana Gist system 1MB limit cross kar chuka tha → history read fail + wipe-on-write bug
- **Auth add hua:** room passcode + signed session tokens (ab koi random visitor API use nahi kar sakta)

### ✨ Added
- Supabase Postgres: unlimited messages, race-free writes, incremental sync (`/sync/pending`)
- Supabase Storage: private bucket + signed URLs (files ab DB me base64 nahi store hoti)
- Real presence (online users) — DB-backed, har serverless instance se sahi dikhta hai
- `GET /api/qr` — offline QR code generation (pehle 404 tha)
- `/auth/join`, `/auth/rename` — verified identity, name-change system broadcast
- `/view_once/reveal/{id}` — view-once ab SERVER-side enforced hai
- Soft deletes + `updated_at` trigger — race-free sync, deletions sab devices par propagate hote hain
- Setup screen — env vars missing hone par frontend friendly instructions dikhata hai
- `supabase_setup.sql`, `.env.example`, `LICENSE` (MIT), GitHub Actions CI
- `migrate_from_gist.py` — purane Gist messages/files Supabase me shift karne ka script

### 🐛 Fixed
- **Missing `</div>`** — poora input dock (message box + send) `display:none` overlay ke andar chhupa tha
- Silent data loss: fire-and-forget gist writes (threads) → sab writes awaited + DB-backed
- Private DMs ab server-side filtered (pehle `/history` anonymous call se sab padh sakte tha)
- Delete ownership ab server-verified (pehle `sender` param skip karke koi bhi delete kar sakta tha)
- Stored XSS via `/react` emoji → strict server-side emoji whitelist
- Timestamps 5.5 ghante off the (UTC parse bug) → ab ISO-8601 with `Z`, local me sahi render
- Duplicate stylesheet load hataya
- CORS hardening (same-origin default, optional allowlist)
- Cold-start par module-level network calls hataye (fast boot)

### 🗑️ Removed
- `/api/download-all-zip` (dead button — Vercel 4.5MB response limit me fit nahi hota tha)
- Hardcoded GitHub token & Gist ID (⚠️ purana token revoke karna na bhoolen!)

### ⬆️ Upgrade guide
Purane version se aane walon ke liye → README.md ka **"Migration"** section dekho.
