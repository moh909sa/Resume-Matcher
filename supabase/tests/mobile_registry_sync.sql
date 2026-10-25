-- Run in a transaction and roll back all fixtures.
begin;
insert into auth.users(id) values
 ('7216fbb1-0367-4d9a-9d4f-c2b51a72ab81'),
 ('7216fbb1-0367-4d9a-9d4f-c2b51a72ab82');
set local role service_role;
select public.reserve_user_resume(
 '7216fbb1-0367-4d9a-9d4f-c2b51a72ab81','215393b5-91ac-4cf6-9ee7-cff3b368aa81',
 'a.pdf','7216fbb1-0367-4d9a-9d4f-c2b51a72ab81/215393b5-91ac-4cf6-9ee7-cff3b368aa81/original.pdf',
 'application/pdf',1);
select public.reserve_user_resume(
 '7216fbb1-0367-4d9a-9d4f-c2b51a72ab82','215393b5-91ac-4cf6-9ee7-cff3b368aa82',
 'b.pdf','7216fbb1-0367-4d9a-9d4f-c2b51a72ab82/215393b5-91ac-4cf6-9ee7-cff3b368aa82/original.pdf',
 'application/pdf',1);
select public.sync_user_resume_registry(
 '7216fbb1-0367-4d9a-9d4f-c2b51a72ab81',
 '[{"resume_id":"215393b5-91ac-4cf6-9ee7-cff3b368aa81","processing_status":"ready","updated_at":"2026-10-25T12:00:02Z","is_default_master":true},{"resume_id":"215393b5-91ac-4cf6-9ee7-cff3b368aa82","processing_status":"ready","updated_at":"2026-10-25T12:00:02Z","is_default_master":true}]',
 '2026-10-25T12:00:02Z');
select public.sync_user_resume_registry(
 '7216fbb1-0367-4d9a-9d4f-c2b51a72ab81',
 '[{"resume_id":"215393b5-91ac-4cf6-9ee7-cff3b368aa81","processing_status":"failed","updated_at":"2026-10-25T12:00:01Z","is_default_master":false}]',
 '2026-10-25T12:00:01Z');
do $$
declare r public.user_resumes; extra uuid; n integer;
begin
 select * into r from public.user_resumes where id='215393b5-91ac-4cf6-9ee7-cff3b368aa81';
 if r.processing_status <> 'ready' or not r.is_default then raise exception 'Older snapshot overwrote newer state'; end if;
 select * into r from public.user_resumes where id='215393b5-91ac-4cf6-9ee7-cff3b368aa82';
 if r.processing_status <> 'pending' or r.is_default then raise exception 'Other user snapshot was modified'; end if;
 for n in 1..4 loop
   extra := gen_random_uuid();
   perform public.reserve_user_resume(
     '7216fbb1-0367-4d9a-9d4f-c2b51a72ab81',extra,'quota.pdf',
     '7216fbb1-0367-4d9a-9d4f-c2b51a72ab81/' || extra::text || '/original.pdf','application/pdf',1);
 end loop;
 begin
   extra := gen_random_uuid();
   perform public.reserve_user_resume(
     '7216fbb1-0367-4d9a-9d4f-c2b51a72ab81',extra,'sixth.pdf',
     '7216fbb1-0367-4d9a-9d4f-c2b51a72ab81/' || extra::text || '/original.pdf','application/pdf',1);
   raise exception 'Sixth reservation was accepted';
 exception when sqlstate 'PT409' then null;
 end;
end $$;
reset role;
do $$
begin
 if has_function_privilege('anon','public.sync_user_resume_registry(uuid,jsonb,timestamptz)','EXECUTE')
   or has_function_privilege('authenticated','public.sync_user_resume_registry(uuid,jsonb,timestamptz)','EXECUTE')
   or has_function_privilege('authenticated','public.reserve_user_resume(uuid,uuid,text,text,text,integer)','EXECUTE')
   or has_function_privilege('anon','public.reserve_user_resume(uuid,uuid,text,text,text,integer)','EXECUTE')
 then raise exception 'Client can call a server-only function'; end if;
end $$;
select 'RPC ownership, fencing, quota and client privilege assertions passed' as test_result;
rollback;

