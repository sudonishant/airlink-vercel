<div align="center">

# ✈️ AirLink

**Private, real-time chat + file sharing — apne devices aur doston ke saath, kahin bhi.**

Telegram-style UI • PWA (installable) • Photos, Files & Voice Notes • Private DMs • View-Once • Emoji Reactions • Online Presence

`Vercel Serverless` + `Supabase (Postgres + Storage)` — **₹0 pe chalta hai**

</div>

---

## 📖 Ye kya hai?

AirLink ek lightweight private chat app hai — phone, PC, doston ke beech instant messages, photos, files aur voice notes bhejne ke liye. Install karo (PWA), passcode se join karo, aur chatting shuru.

**v2.0 ek complete production rebuild hai** — purana version GitHub Gist ko database ki tarah use karta tha jo 1MB limit cross karke toot gaya tha (messages gayab ho rahe the). Naya version proper database + file storage use karta hai.

| | Purana (v1 — Gist) | Naya (v2 — Supabase) |
|---|---|---|
| Messages | 1MB JSON file (toot gaya) | ♾️ Postgres database |
| Files | base64 DB me (max ~700KB) | 📦 Storage bucket (4MB, proper URLs) |
| Live updates | 1s polling, 30s stale data | ⚡ 2s incremental sync (fresh) |
| Online users | ❌ Kaam nahi karta tha | ✅ DB-backed presence |
| Security | ❌ Token source me leaked, sab public | 🔒 Room passcode + verified identity |
| Private DMs | ❌ API se sab padh sakte the | 🔒 Server-side enforced |
| Data loss | ❌ Silent wipes | ✅ Proper transactions |

---

## 🚀 Setup (10 minute, ek baar)

### Step 1 — Supabase project banao (free)

1. [supabase.com](https://supabase.com) par jao → **Sign up** (GitHub se kar sakte ho)
2. **New Project** → naam `airlink` → strong database password → region **Mumbai (ap-south-1)** chuno → Create
3. Project banne ke baad: **SQL Editor** → **New query** → poora `supabase_setup.sql` (is repo me hai) paste karo → **Run** ✅

### Step 2 — Keys copy karo

Supabase → **Settings → API** se:

| Key | Kahan milega |
|---|---|
| `Project URL` | Settings → API → Project URL |
| `service_role` key | Settings → API → `service_role (secret)` ⚠️ |

### Step 3 — Vercel me Environment Variables set karo

Vercel Dashboard → aapka `airlink` project → **Settings → Environment Variables** (Production + Preview + Development teeno me):

| Variable | Value |
|---|---|
| `SUPABASE_URL` | Step 2 ka Project URL |
| `SUPABASE_SERVICE_KEY` | Step 2 ka service_role key |
| `ROOM_PASSCODE` | Apni pasand ka strong passcode (doston ke saath yahi share hoga) |

> ⚠️ `service_role` key **kabhi** git commit ya frontend me mat bhejna — ye full admin access hai. Sirf Vercel env vars me.

### Step 4 — Deploy

```bash
git add -A && git commit -m "AirLink v2.0 — production rebuild" && git push
```

GitHub connected hai to Vercel automatic deploy kar dega. Kuch env var missing raha to app khud ek friendly **Setup screen** dikhayega.

### Step 5 — Purana data migrate karo (optional)

Purane Gist version ke messages chahiye to:

```bash
# backup file repo ke bahar hai — ya gist raw URL use karo
export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_SERVICE_KEY="eyJ..."
python3 migrate_from_gist.py --dry-run    # pehle dekho
python3 migrate_from_gist.py              # asli migration
```

### Step 6 — Join karo

App kholo → apna naam + room passcode daalo → chat shuru 🎉 Phone par **Add to Home Screen** karo — native app jaisa chalega.

---

## 🏗️ Architecture

```
┌─────────────┐         ┌──────────────────────────┐
│   Browser   │◀──2s───▶│  Vercel Serverless (Py)  │
│  PWA (vanilla│  sync   │  FastAPI  api/index.py   │
│  HTML/JS/CSS)│         └───────────┬──────────────┘
└─────────────┘                     │ REST (service key)
                                    ▼
                    ┌───────────────────────────────┐
                    │           Supabase            │
                    │  • Postgres: messages,        │
                    │    presence, app_state        │
                    │  • Storage: files (private    │
                    │    bucket + signed URLs)      │
                    └───────────────────────────────┘
```

**Kyun ye design:**

- **No build step** — vanilla JS/CSS, zero dependencies frontend me. Simple = reliable.
- **Serverless-safe** — koi in-memory state nahi (purane version ki sabse badi galti), koi background threads nahi, sab writes awaited.
- **Incremental sync** — har poll sirf `updated_at > since` wali rows laata hai (soft deletes + trigger ke through). Race-free.
- **Files storage me, DB me nahi** — signed URLs (6h expiry) direct Supabase CDN se serve hoti hain, function ke through proxy nahi.

## 🔐 Security model

- **Room passcode** — URL jaan bhaad ke koi bhi chat padh/likh nahi sakta. Har API call verified HMAC-signed token maangta hai.
- **Verified identity** — token me naam embedded hai; sender spoof nahi ho sakta. Delete sirf apne messages (server-enforced).
- **Private DMs** — server-side filter: sirf sender aur recipient ko rows milti hain.
- **View-once** — content server par hi unlock hota hai (`/view_once/reveal`), ek baar consume = permanently locked (410).
- **RLS on, zero policies** — tables ko sirf service key (aapka backend) access kar sakta hai; anon key se kuch nahi.
- **XSS-proof** — reactions emoji server-side whitelist se; message text `textContent` se render hota hai.
- **Clear-all** — admin action, room passcode maangta hai.

> 📝 Note: room ke andar ek hi passcode sabke paas hai, to room members ek doosre ka naam **assume** kar ke join kar sakte hain. Maximum privacy chahiye to har user apna alag Supabase Auth use kare (roadmap me hai).

## ⚠️ Limits (jo pata hona chahiye)

- **File size: 4MB** — Vercel serverless request limit (~4.5MB) ki wajah se. Bade files ke liye direct-to-storage presigned uploads roadmap me hai.
- **Polling: 2 second** — Supabase Realtime websockets ke saath instant ho sakta hai (roadmap).
- **History: last 300 messages** load hoti hain (pagination roadmap me).
- Free tier limits: Supabase (500MB DB / 1GB storage), Vercel Hobby (100GB bandwidth/month) — personal use ke liye 10x zyada.

## 🗺️ Roadmap ideas

- [ ] Supabase Realtime (websockets) — instant updates, zero polling
- [ ] Presigned direct uploads — 50MB tak files
- [ ] Supabase Auth — per-user login, sach me private DMs
- [ ] Message pagination + infinite scroll
- [ ] Typing indicators, delivery/read receipts
- [ ] Storage cleanup cron (soft-deleted files)
- [ ] Hindi/English language toggle

## 🛠️ Local development

```bash
pip install -r requirements.txt
export SUPABASE_URL="..." SUPABASE_SERVICE_KEY="..." ROOM_PASSCODE="dev"
uvicorn api.index:app --reload --port 8000
# static: public/ folder serve karo (e.g. `python3 -m http.server 5500 -d public`)
```

## 📁 Project structure

```
├── api/index.py            # Poora backend (FastAPI — single function)
├── public/                 # Frontend (vanilla — no build step)
│   ├── index.html          # App shell
│   ├── js/app.js           # Saara client logic
│   ├── css/style.css       # Telegram-style theme
│   ├── manifest.json       # PWA manifest
│   └── sw.js               # Service worker (network-first)
├── supabase_setup.sql      # One-time DB setup (Step 1 me run hota hai)
├── migrate_from_gist.py    # v1 → v2 data migration
├── vercel.json             # Routing + function config
├── requirements.txt        # Python deps (5 packages)
├── .env.example            # Environment variable reference
└── .github/workflows/ci.yml  # Lint + syntax checks har push par
```

## 📜 License

[MIT](LICENSE) © 2026 sudonishant

---

<div align="center">

**Agar ye project useful laga to ⭐ star zaroor dena!**

</div>
