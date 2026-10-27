-- Owner-scoped, durable status of an in-flight mobile Resume-Matcher run.
-- Actual engine stage updates are mirrored by the same Railway process that
-- executes the AI task; any replica may serve an authenticated status GET.
create table if not exists public.user_tailoring_progress (
    id uuid primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    source_resume_id uuid references public.user_resumes(id) on delete set null,
    status text not null default 'running'
        check (status in ('running', 'succeeded', 'failed')),
    stage text not null default 'starting',
    current_step text,
    completed_steps jsonb not null default '[]'::jsonb
        check (jsonb_typeof(completed_steps) = 'array'),
    visited_steps jsonb not null default '[]'::jsonb
        check (jsonb_typeof(visited_steps) = 'array'),
    tailoring_id uuid references public.user_tailored_cvs(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    finished_at timestamptz
);
create index if not exists idx_user_tailoring_progress_owner_date
    on public.user_tailoring_progress (user_id, created_at desc);

alter table public.user_tailoring_progress enable row level security;
revoke all on public.user_tailoring_progress from public, anon, authenticated;
grant select on public.user_tailoring_progress to authenticated;
grant all on public.user_tailoring_progress to service_role;
create policy "owners can read their tailoring progress"
    on public.user_tailoring_progress for select to authenticated
    using ((select auth.uid()) = user_id);
comment on table public.user_tailoring_progress is
    'Privacy-safe stage timeline. No job description, CV text, or access token is stored here; trusted server writes only.';
