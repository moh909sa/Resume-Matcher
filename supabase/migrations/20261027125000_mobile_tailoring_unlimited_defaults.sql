-- Mobile tailoring: No Limit and All are true defaults, not 2 pages / 5 bullets.
-- Existing saved tailoring records retain their explicit preferences.
alter table public.user_tailored_cvs
  alter column max_pages drop not null,
  alter column max_pages drop default,
  alter column max_bullets_per_entry drop not null,
  alter column max_bullets_per_entry drop default;

comment on column public.user_tailored_cvs.max_pages is
  'NULL = no page limit or page fitting; 2/3 = explicit page budget.';
comment on column public.user_tailored_cvs.max_bullets_per_entry is
  'NULL = keep all source bullet points; 3/5 = explicit per-entry cap.';
