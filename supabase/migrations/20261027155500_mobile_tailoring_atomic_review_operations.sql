alter table public.user_tailored_cvs add column if not exists operation_token uuid;
alter table public.user_tailored_cvs add column if not exists operation_until timestamptz;
comment on column public.user_tailored_cvs.operation_token is
  'Server-only temporary claim while applying keywords or confirming a draft.';
comment on column public.user_tailored_cvs.operation_until is
  'Lease expiration, allowing recovery after a crashed request.';