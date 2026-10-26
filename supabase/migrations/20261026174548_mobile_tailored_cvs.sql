-- Authenticated mobile AI tailoring preview/confirmation registry.
create table if not exists public.user_tailored_cvs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  source_resume_id uuid references public.user_resumes(id) on delete set null,
  engine_resume_id uuid unique,
  job_id uuid not null,
  job_description text not null check (char_length(job_description) between 50 and 12000),
  job_title text,
  company text,
  max_pages smallint not null default 2 check (max_pages in (2, 3)),
  max_bullets_per_entry smallint not null default 5 check (max_bullets_per_entry in (3, 5)),
  prompt_id text not null default 'full' check (prompt_id = 'full'),
  status text not null default 'draft' check (status in ('draft', 'ready')),
  preview_id text,
  preview_expires_at timestamptz,
  preview_json jsonb not null default '{}'::jsonb,
  result_json jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_tailored_ready_check check (
    status <> 'ready' or (engine_resume_id is not null and result_json is not null)
  )
);
create index if not exists idx_user_tailored_cvs_owner_created
  on public.user_tailored_cvs (user_id, created_at desc);
alter table public.user_tailored_cvs enable row level security;
revoke all on public.user_tailored_cvs from public, anon, authenticated;
grant select on public.user_tailored_cvs to authenticated;
grant all on public.user_tailored_cvs to service_role;
create policy "owners read their tailored cvs"
  on public.user_tailored_cvs for select to authenticated
  using ((select auth.uid()) = user_id);
comment on table public.user_tailored_cvs is
  'Authenticated mobile tailoring previews and approved outputs. Only trusted Railway service writes; owners can read.';
