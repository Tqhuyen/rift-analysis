-- Rift Report — Supabase schema
-- Run once in the Supabase SQL editor (Dashboard → SQL → New query).
-- Safe to re-run: uses IF NOT EXISTS / OR REPLACE.
--
-- Tables are prefixed with rift_ so they can live in a shared project.
-- Writes use the service-role key from server.py / rift_db.py (server-side only).
-- Public/anon access is read-only.

create table if not exists public.rift_players (
  puuid       text primary key,
  name        text not null,
  tag         text not null default '',
  role        text not null default '',
  c1          text,
  c2          text,
  updated_at  timestamptz not null default now()
);

create table if not exists public.rift_matches (
  game_id       bigint primary key,
  queue_id      integer not null default 2400,
  played_at     timestamptz not null,
  duration      integer not null default 0,
  game_version  text not null default '',
  source        text not null default 'lcu',
  created_at    timestamptz not null default now()
);

create table if not exists public.rift_participants (
  game_id      bigint not null references public.rift_matches(game_id) on delete cascade,
  puuid        text not null references public.rift_players(puuid) on delete cascade,
  champion     text not null,
  win          boolean not null default false,
  kills        integer not null default 0,
  deaths       integer not null default 0,
  assists      integer not null default 0,
  damage       bigint not null default 0,
  gold         bigint not null default 0,
  cs           integer not null default 0,
  champ_level  integer not null default 0,
  team_id      integer,
  augments     jsonb not null default '[]'::jsonb,
  primary key (game_id, puuid)
);

create index if not exists rift_matches_played_at_idx
  on public.rift_matches (played_at desc);
create index if not exists rift_parts_puuid_idx
  on public.rift_participants (puuid);
create index if not exists rift_parts_champion_idx
  on public.rift_participants (champion);

-- Keep updated_at fresh for players.
create or replace function public.rift_touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists rift_players_touch on public.rift_players;
create trigger rift_players_touch
  before update on public.rift_players
  for each row execute function public.rift_touch_updated_at();

-- Read-only access for clients; service role bypasses RLS for writes.
alter table public.rift_players      enable row level security;
alter table public.rift_matches      enable row level security;
alter table public.rift_participants enable row level security;

drop policy if exists "rift players read" on public.rift_players;
create policy "rift players read" on public.rift_players
  for select using (true);

drop policy if exists "rift matches read" on public.rift_matches;
create policy "rift matches read" on public.rift_matches
  for select using (true);

drop policy if exists "rift participants read" on public.rift_participants;
create policy "rift participants read" on public.rift_participants
  for select using (true);

grant usage on schema public to anon, authenticated;
grant select on public.rift_players, public.rift_matches, public.rift_participants
  to anon, authenticated;
