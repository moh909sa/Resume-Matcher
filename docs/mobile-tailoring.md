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
4. **Review wizard:** Once POST /tailor/preview succeeds, automatically open the
   iOS review flow, with no additional "open review" button. The previous AI
   processing screen transitions only when the API returns successfully.
   Client should use the additive `review` field (and original `preview`
   remains intact), or call `GET /tailor/{tailoring_id}/review` to reload
   the authenticated owner's current draft. It provides:
   - `step_order`: `["keywords","changes","confirm"]`
   - `preview_id` and `preview_expires_at`
   - `keyword_options.supported`, `needs_attestation`, `applied`, `remaining_slots`
   - `ats_score`, `score_history` and real `keyword_placements`
   - `change_summary` five color-card counts + total, and `change_sections`
     with real section-specific Before/After changes
   - `warnings` for incomplete diffs or other engine concerns.

   **Step 1 — Optimize Keywords**
   * Show ATS *estimate* from the engine, not a fabricated score. The score may
     rise, fall, or remain unchanged after each application.
   * Show `supported` skills as existing master skills that could be highlighted;
     `needs_attestation` items require explicit user affirmation "I have this".
     Clearly warn: "Select only skills you genuinely have; expect questions
     about them in interviews." A checkbox selection is never an automatic
     claim about the original CV.
   * POST `/tailor/{tailoring_id}/keywords` with JSON:
     `{"expected_preview_id":"<current preview.preview_id>","keywords":[{"keyword":"OPC-UA","attested":true}]}`
   * For supported terms, use `attested:false`; for missing-from-master
     terms user must choose `attested:true`. The server validates ownership,
     latest preview, and whether each term appears in the JOB's suggestions.
   * Returns an updated unsaved `preview`, `review`, and a **new preview_id**.
     Render the new ATS estimate, placements, summary cards, and updated
     suggestions immediately. The user can apply again with the NEW preview_id,
     or skip keywords and press "Continue".
   * Never keep using an old preview_id or invent improvement percentages.
     Max 30 distinct applied keywords per draft. A 409 means the preview is
     stale, expired or another request is running: fetch /review to refresh.
     422 means invalid/repeated/unsupported keyword selection.
   * The original CV is NOT changed. Do NOT show or implement a "Also add to
     master" default; this feature intentionally operates only on the draft.

   **Step 2 — Review Changes**
   * Display `change_summary` cards for Skills Added / Skills Removed /
     Certifications Added / Descriptions Modified / High Risk Changes.
   * Expand `change_sections` in clear, mobile-friendly accordions; show
     old and new text, additions/deletions, and high-risk warnings.
     Missing diff data is a warning, not implicit acceptance.
   * User can go back to Keywords and apply more, then review the *latest* diff.

   **Step 3 — Confirm & Save**
   * Explain that the user's original CV remains unchanged.
   * User explicitly taps Confirm & Save. No automatic confirmation.
   * Handle temporary busy / retriable 409 states; never save an older preview.

5. On approval: POST `/tailor/{tailoring_id}/confirm` with no JSON body.
   The server atomically claims and confirms the latest stored draft and returns `status=ready` and
   `tailored_cv`. Retry after transient failures; confirmation is replay-safe.
6. GET `/tailored-cvs` lists owned saved/draft CVs (without large content).
   GET `/tailored-cvs/{tailoring_id}` returns the owned preview/result.
   The original CV is not overwritten. Concurrent keyword/confirm requests are serialized with a crash-recoverable 15-minute database lease.

For preview errors, no fake output is stored. Jobs linked to unusable previews
are cleaned up. Expired previews require generating a new one. Both authentication
and original-CV ownership are verified by Railway. No secret key ships with iOS.
The Supabase `user_tailored_cvs` table has RLS; only the backend writes.

**Before enabling production billing:** introduce subscription/usage limits,
proper idempotent reservations and async jobs for long-running generations. The
current preview request is synchronous and can take up to the server timeout.

## Real-time iOS progress — owner-scoped polling (October 27, 2026)

The **existing POST** `/api/v1/mobile/tailor/preview` remains synchronous, so
existing mobile clients continue to function. New clients may send an optional
fresh, random UUID v4 `progress_id` in the same JSON body with `resume_id`
and `job_description`. This is for status monitoring only, not authorization.

When the customer taps **Tailor My CV**:

1. Generate a fresh UUID v4 before the POST. Start POST /tailor/preview with
   `{"resume_id":"...","job_description":"...","progress_id":"<uuid>"}`.
   Keep that POST alive and pending until it returns the actual preview.
2. While the POST is running, GET
   `/api/v1/mobile/tailor/progress/<uuid>` every **1.5–2 seconds** using the
   *same* `Authorization: Bearer <Supabase access token>` header. The GET
   starts working once the POST registers the run. A short initial 404 is
   permitted; retry briefly. Different users cannot read a run.
3. The response is light: `{progress_id,status,current_step,completed_steps,
   visited_steps,tailoring_id,started_at,updated_at}`. The status is
   `running`, `succeeded`, or `failed`.
4. UI labels for the seven progress steps (in order):
   - `read_job`: Read the job
   - `plan_skills`: Plan the skills to show
   - `tailor_resume`: Tailor the resume
   - `keywords_facts`: Work in keywords and check facts
   - `critique_writing`: Critique the writing
   - `rewrite_lines`: Rewrite weak lines
   - `verify_review`: Verify and prepare the review
5. Green checks **only** for `completed_steps` sent by the server. Animate
   exactly `current_step` while `running`. Leave non-visited steps muted
   (a stage can be legitimately skipped). Never invent stage completion,
   percent, expected completion time, or an animated fake progress percentage.
   The elapsed timer starts at zero and continues independently of status.
6. On successful **POST /tailor/preview**, stop polling and automatically
   `router.replace("/tailoring/review")`, preserving the returned preview
   and all user inputs, just as before. Do NOT wait for polling's final packet:
   the POST is authoritative for success and returns the actual review data.
   On POST error stop polling and show a Retry option with inputs preserved.
   If status GET temporarily fails, retain the spinner and timer instead of
   reporting phantom progress.
7. Existing preview defaults (Full Tailor / No Limit / All) and the current
   review, iterative keywords, Confirm & Save workflow stay unchanged.

**Implementation:** `services/progress.py` captures *every* engine stage
transition (even fast ones). A lightweight mirror in the **same Railway process**
persists only changed stage sequences to `user_tailoring_progress` in Supabase.
This allows authenticated GET polling from any Railway replica. Only the
trusted server may write to that table; owner RLS permits reading. No CV text,
job description, API secrets or prompt logs are written there. No new LLM calls
are made for progress updates. This is not a durable background job; the
existing POST must complete for its resume preview to be delivered.

