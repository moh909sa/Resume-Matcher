-- Server-only synchronization; newer engine/default snapshots win.
alter table public.user_resumes add column engine_updated_at timestamptz;
create table private.resume_registry_versions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  observed_at timestamptz not null
);
alter table private.resume_registry_versions enable row level security;
revoke all on private.resume_registry_versions from public, anon, authenticated;
grant usage on schema private to service_role;
grant select, insert, update, delete on private.resume_registry_versions to service_role;

create function public.sync_user_resume_registry(p_user_id uuid, p_snapshot jsonb, p_observed_at timestamptz)
returns void language plpgsql security invoker set search_path = '' as $$
declare accepted boolean; selected_id uuid;
begin
  if p_user_id is null or p_observed_at is null or p_snapshot is null or jsonb_typeof(p_snapshot) <> 'array' then
    raise exception 'Invalid registry snapshot';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_user_id::text, 20261025));
  update public.user_resumes r
  set processing_status = s.processing_status, engine_updated_at = s.updated_at
  from jsonb_to_recordset(p_snapshot) as s(resume_id uuid, processing_status text, updated_at timestamptz)
  where r.user_id = p_user_id and r.engine_resume_id = s.resume_id
    and s.processing_status in ('pending', 'processing', 'ready', 'failed')
    and (r.engine_updated_at is null or r.engine_updated_at < s.updated_at);
  insert into private.resume_registry_versions as v (user_id, observed_at)
  values (p_user_id, p_observed_at)
  on conflict (user_id) do update set observed_at = excluded.observed_at
  where v.observed_at <= excluded.observed_at returning true into accepted;
  if coalesce(accepted, false) then
    select r.id into selected_id from public.user_resumes r
    join jsonb_to_recordset(p_snapshot) as s(resume_id uuid, is_default_master boolean)
      on r.engine_resume_id = s.resume_id
    where r.user_id = p_user_id and s.is_default_master limit 1;
    update public.user_resumes set is_default = false
      where user_id = p_user_id and is_default and (selected_id is null or id <> selected_id);
    update public.user_resumes set is_default = true
      where user_id = p_user_id and id = selected_id and not is_default;
  end if;
end;
$$;
revoke all on function public.sync_user_resume_registry(uuid,jsonb,timestamptz) from public, anon, authenticated;
grant execute on function public.sync_user_resume_registry(uuid,jsonb,timestamptz) to service_role;
comment on function public.sync_user_resume_registry(uuid,jsonb,timestamptz) is
  'Server only. Derive user ID from verified Supabase Auth, never a client payload.';
notify pgrst, 'reload schema';

create function public.reserve_user_resume(
  p_user_id uuid, p_resume_id uuid, p_filename text, p_storage_path text,
  p_mime_type text, p_file_size integer
)
returns setof public.user_resumes
language plpgsql security invoker set search_path = '' as $$
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_user_id::text, 20261025));
  if (select count(*) from public.user_resumes where user_id = p_user_id) >= 5 then
    raise exception using errcode = 'PT409', message = 'Original resume limit reached';
  end if;
  return query insert into public.user_resumes
    (id,user_id,engine_resume_id,original_filename,storage_path,mime_type,file_size_bytes)
  values (p_resume_id,p_user_id,p_resume_id,p_filename,p_storage_path,p_mime_type,p_file_size)
  returning *;
end;
$$;
revoke all on function public.reserve_user_resume(uuid,uuid,text,text,text,integer) from public, anon, authenticated;
grant execute on function public.reserve_user_resume(uuid,uuid,text,text,text,integer) to service_role;
comment on function public.reserve_user_resume(uuid,uuid,text,text,text,integer) is
  'Server only. Atomically reserves at most five originals per verified user before any file or AI work.';
