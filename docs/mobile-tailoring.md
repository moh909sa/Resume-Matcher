# Mobile AI tailoring contract (iOS / Draftbit)

Requires Supabase Auth bearer access token, the same as original CV APIs.
Base path: `/api/v1/mobile`. Do not call legacy `/api/v1/jobs` or
`/api/v1/resumes/improve` from mobile: they are intentionally blocked.

## User flow
1. Select a `ready` original CV from GET /resumes.
2. Paste a job description (50–12,000 characters). Job URL is out of scope.
3. POST `/tailor/preview` with JSON:
   `{"resume_id":"<original UUID>","job_description":"..."}`
   * Length options are **optional**. By default, `max_pages=null` (No Limit:
     no forced page fitting) and `max_bullets_per_entry=null` (All: no
     artificial bullet cap). Omitting both options is recommended for iOS.
     If explicitly chosen later, `max_pages` can be 2 or 3 and
     `max_bullets_per_entry` can be 3 or 5.
     No Limit does **not** guarantee a 2- or 3-page result.
   * Intensity is always forced to `full` **on the server**, not client-supplied.
   * Returns `tailoring_id`, `status=draft`, `preview` (resume_preview,
     detailed_changes, warnings, preview_expires_at), and `preferences`.
   * Page fitting runs only when a page cap is explicitly requested. When
     requested, it uses a short-lived print draft and a loopback-only
     internal API route. Show any warnings; never promise an exact page count.
4. Show the preview/diff for user review; DO NOT auto-confirm.
5. On approval: POST `/tailor/{tailoring_id}/confirm` with no JSON body.
   The server confirms the exact stored draft and returns `status=ready` and
   `tailored_cv`. Retry after transient failures; confirmation is replay-safe.
6. GET `/tailored-cvs` lists owned saved/draft CVs (without large content).
   GET `/tailored-cvs/{tailoring_id}` returns the owned preview/result.
   The original CV is not overwritten.

For preview errors, no fake output is stored. Jobs linked to unusable previews
are cleaned up. Expired previews require generating a new one. Both authentication
and original-CV ownership are verified by Railway. No secret key ships with iOS.
The Supabase `user_tailored_cvs` table has RLS; only the backend writes.

**Before enabling production billing:** introduce subscription/usage limits,
proper idempotent reservations and async jobs for long-running generations. The
current preview request is synchronous and can take up to the server timeout.
