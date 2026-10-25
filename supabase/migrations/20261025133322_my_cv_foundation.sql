-- My CV foundation for tailoring-resume.
-- Resume Matcher stays on Railway; the bridge ID is server-managed.
-- All originals live in the private resume-files bucket.

create schema private;
revoke all on schema private from public, anon, authenticated;

-- Keep the existing automatic-RLS event trigger, but do not expose it as an RPC.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;

create function private.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at = pg_catalog.now();
  return new;
end;
$$;
revoke all on function private.set_updated_at() from public, anon, authenticated;

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text check (display_name is null or char_length(display_name) between 1 and 100),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.profiles enable row level security;

create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function private.set_updated_at();

revoke all on table public.profiles from public, anon, authenticated;
grant select on public.profiles to authenticated;
grant insert (id, display_name) on public.profiles to authenticated;
grant update (display_name) on public.profiles to authenticated;
grant select, insert, update, delete on public.profiles to service_role;

create policy profiles_select_own
on public.profiles for select to authenticated
using ((select auth.uid()) = id);

create policy profiles_insert_own
on public.profiles for insert to authenticated
with check ((select auth.uid()) = id);

create policy profiles_update_own
on public.profiles for update to authenticated
using ((select auth.uid()) = id)
with check ((select auth.uid()) = id);

create table public.user_resumes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  display_name text check (display_name is null or char_length(display_name) between 1 and 200),
  original_filename text not null check (char_length(original_filename) between 1 and 255),
  storage_bucket text not null default 'resume-files' check (storage_bucket = 'resume-files'),
  storage_path text not null unique,
  mime_type text not null check (mime_type in (
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  )),
  file_size_bytes integer not null check (file_size_bytes between 1 and 4194304),
  engine_resume_id uuid unique,
  processing_status text not null default 'pending'
    check (processing_status in ('pending', 'processing', 'ready', 'failed')),
  is_default boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_resumes_owner_storage_path
    check (split_part(storage_path, '/', 1) = user_id::text
      and char_length(storage_path) > char_length(user_id::text) + 1),
  constraint user_resumes_ready_has_engine_id
    check (processing_status <> 'ready' or engine_resume_id is not null)
);
alter table public.user_resumes enable row level security;

create index user_resumes_owner_created_idx
on public.user_resumes (user_id, created_at desc);

create unique index user_resumes_one_default_per_user
on public.user_resumes (user_id) where is_default;

create trigger user_resumes_set_updated_at
before update on public.user_resumes
for each row execute function private.set_updated_at();

-- The client may read its own records. Railway will perform writes after
-- validating the JWT and ownership. Clients must never assign engine IDs.
revoke all on table public.user_resumes from public, anon, authenticated;
grant select on public.user_resumes to authenticated;
grant select, insert, update, delete on public.user_resumes to service_role;

create policy user_resumes_select_own
on public.user_resumes for select to authenticated
using ((select auth.uid()) = user_id);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'resume-files', 'resume-files', false, 4194304,
  array['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
);

-- Server uploads use <user_id>/<resume_id>/original.pdf or original.docx.
-- Folder ownership also works when server uploads have no owner_id.
create policy resume_files_select_own
on storage.objects for select to authenticated
using (
  bucket_id = 'resume-files'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);

comment on table public.profiles is
  'App profile only. Supabase Auth owns login credentials. Profiles are created on first use, not by an Auth trigger.';
comment on table public.user_resumes is
  'Original CV registry. All writes, engine IDs and processing status are server-managed after JWT and ownership checks. Tailored results will have a separate schema.';
comment on column public.user_resumes.engine_resume_id is
  'Resume Matcher ID on Railway; nullable until the backend creates the engine record. Never accept a client-assigned engine ID.';
comment on column public.user_resumes.storage_path is
  'Object key in the private resume-files bucket. First folder is the Supabase Auth user ID. File cleanup must use Storage API.';
comment on column public.user_resumes.is_default is
  'At most one default original per user. Default switching must be transactional in the backend.';

notify pgrst, 'reload schema';

