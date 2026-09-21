-- ============================================================
-- AirLink v2.0 — Supabase Setup (one-time, 30 seconds)
-- ============================================================
-- Kahan run karein:
--   1. https://supabase.com → New Project (free tier) banayein
--   2. Project → SQL Editor → New query
--   3. Ye poora file paste karke "Run" dabayein
--
-- Note: RLS (Row Level Security) enabled hai with NO public policies —
-- matlab koi bhi public/anon key se data NAHI padh sakta.
-- Sirf aapka backend (service key) access karta hai. Fully private. 🔒
-- ============================================================

-- ---------- Messages table ----------
create table if not exists public.messages (
  id            text primary key,
  type          text not null default 'text',          -- text | file | system
  category      text not null default 'text',          -- text | image | video | audio | archive | document | other | system
  content       text,                                  -- text content (NULL for files)
  filename      text,
  original_name text,
  file_size     bigint,
  formatted_size text,
  mime_type     text,
  storage_path  text,                                  -- Supabase Storage object path
  sender        text not null,
  recipient     text,                                  -- DM target (NULL = public)
  is_private    boolean not null default false,
  is_view_once  boolean not null default false,
  is_consumed   boolean not null default false,
  deleted       boolean not null default false,        -- soft delete (sync-safe)
  reactions     jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  time_epoch    double precision not null default 0
);

create index if not exists idx_messages_time     on public.messages (time_epoch desc);
create index if not exists idx_messages_updated  on public.messages (updated_at desc);
create index if not exists idx_messages_deleted  on public.messages (deleted) where deleted = false;

-- updated_at auto-bump on every UPDATE (reactions, pin-state, view-once, soft delete)
create or replace function public.bump_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists messages_bump_updated on public.messages;
create trigger messages_bump_updated
  before update on public.messages
  for each row execute function public.bump_updated_at();

-- ---------- Presence table (online users — serverless-safe) ----------
create table if not exists public.presence (
  name      text primary key,
  device    text,
  last_seen double precision not null default 0
);

-- ---------- App state (pinned message id, etc.) ----------
create table if not exists public.app_state (
  key   text primary key,
  value jsonb
);

-- ---------- DB clock (single source of truth for sync) ----------
create or replace function public.db_now()
returns timestamptz language sql as $$
  select now();
$$;

-- ---------- Private Storage bucket (files) ----------
insert into storage.buckets (id, name, public)
values ('airlink', 'airlink', false)
on conflict (id) do nothing;

-- ---------- Lock everything down ----------
alter table public.messages  enable row level security;
alter table public.presence  enable row level security;
alter table public.app_state enable row level security;

-- (No policies created on purpose: only the service-role key —
--  jo sirf aapke Vercel backend ke paas hai — access kar sakta hai.)
