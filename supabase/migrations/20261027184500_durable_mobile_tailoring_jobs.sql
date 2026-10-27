-- Durable background tailoring jobs. Existing completed progress rows are preserved.
ALTER TABLE public.user_tailoring_progress DROP CONSTRAINT IF EXISTS user_tailoring_progress_status_check;
ALTER TABLE public.user_tailoring_progress
  ADD CONSTRAINT user_tailoring_progress_status_check
  CHECK (status IN ('queued','running','succeeded','failed','interrupted'));
ALTER TABLE public.user_tailoring_progress
  ADD COLUMN IF NOT EXISTS job_description text,
  ADD COLUMN IF NOT EXISTS max_pages smallint,
  ADD COLUMN IF NOT EXISTS max_bullets_per_entry smallint,
  ADD COLUMN IF NOT EXISTS claim_token uuid,
  ADD COLUMN IF NOT EXISTS lease_until timestamptz,
  ADD COLUMN IF NOT EXISTS attempts smallint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS error_code text;
ALTER TABLE public.user_tailored_cvs ADD COLUMN IF NOT EXISTS progress_id uuid;
CREATE UNIQUE INDEX IF NOT EXISTS ux_user_tailored_cvs_progress_id
  ON public.user_tailored_cvs (progress_id) WHERE progress_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_one_active_mobile_tailoring_per_user
  ON public.user_tailoring_progress (user_id)
  WHERE status IN ('queued','running') AND job_description IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mobile_tailoring_queue
  ON public.user_tailoring_progress (status, created_at) WHERE job_description IS NOT NULL;
ALTER TABLE public.user_tailoring_progress
  ADD CONSTRAINT user_tailoring_progress_options_check
  CHECK ((max_pages IS NULL OR max_pages IN (2,3))
    AND (max_bullets_per_entry IS NULL OR max_bullets_per_entry IN (3,5))
    AND (job_description IS NULL OR char_length(job_description) BETWEEN 50 AND 12000));
GRANT ALL ON public.user_tailoring_progress TO service_role;
GRANT ALL ON public.user_tailored_cvs TO service_role;
COMMENT ON COLUMN public.user_tailoring_progress.job_description IS
  'Private queue input; never included in progress/status API responses or application logs.';
COMMENT ON COLUMN public.user_tailoring_progress.lease_until IS
  'Worker heartbeat lease; expired in-flight AI is never silently regenerated.';
