# Authenticated CV uploads

The mobile application calls `/api/v1/mobile` with a Supabase user access token
in `Authorization: Bearer <access_token>`. The server validates that session with
Supabase Auth; user IDs never come from request bodies.

## Railway setup

1. Apply the migrations in `supabase/migrations` to the application's Supabase
   project. The original file bucket is `resume-files`, private, with a 4 MiB limit.
2. Set `SUPABASE_URL`, server-only `SUPABASE_SECRET_KEY` (`sb_secret_...`), and
   `MOBILE_API_ENABLED=true` on the Resume-Matcher service.
3. Keep the existing persistent volume at `/app/backend/data`. Customer engine
   records use `resume_matcher.mobile.db`; the existing standalone database keeps
   provider configuration. Keep one replica while using this SQLite deployment.

Mobile mode closes the old unauthenticated standalone APIs, including provider
settings and reset. The health endpoint remains available. Leaving the flag off
preserves standalone behavior. Never put the server secret in Draftbit, Expo,
GitHub, or an `EXPO_PUBLIC_` variable. Client configuration uses the Supabase URL
and publishable key only. Native iOS requests do not require CORS; add an exact
web preview origin to `CORS_ORIGINS` if browser previews need it.

## Screen contract

| Method | Path relative to `/api/v1/mobile` | Purpose |
| --- | --- | --- |
| GET | `/me` | Verify the current account |
| POST | `/resumes/upload` | Multipart `file`: PDF or DOCX, at most 4 MiB |
| GET | `/resumes` | Reload the account's saved CVs, newest first |
| GET | `/resumes/{id}` | Read metadata and processed content |
| GET | `/resumes/{id}/original` | Download the private original |
| PATCH | `/resumes/{id}` | Rename with `{ "display_name": "My CV" }` |
| POST | `/resumes/{id}/default` | Select the original used for future tailoring |
| POST | `/resumes/{id}/retry-processing` | Retry without uploading another copy |
| DELETE | `/resumes/{id}` | Delete the original, registry, and engine record |

The response includes `id`, `original_filename`, `display_name`, `mime_type`,
`file_size_bytes`, `processing_status`, `is_default`, timestamps,
`processed_resume`, and `recovery_required`. Lists return an array. Deletion
returns 204. Each account can save five originals.

Upload processing is synchronous and can take up to the configured request
timeout. On an error, refresh the list before retrying: the original may already
be safely stored with a failed status. Keep it visible and offer processing
retry. A valid provider API key is required to finish AI processing. Uploading
and private storage are separate from processing success.

If the mobile SQLite file is lost, retained Supabase originals can rebuild their
engine records through the retry endpoint. Storage paths are checked against
the verified owner's UUID before server access. An older standalone release
cannot read the separate mobile SQLite file.

## Validation

Backend coverage includes authenticated upload, owner isolation, original-byte
download, retry/recovery, deletion, per-user quota, and separation from the
legacy database. `supabase/tests/mobile_registry_sync.sql` checks SQL privileges,
owner isolation, quotas, and stale synchronization inside a rolled-back
transaction. The foundation authorization tests are kept with the original
Supabase foundation artifact.

On the managed development machine, synthetic Chromium `data:` fixture URLs are
blocked by administrator policy. The full backend suite was run with an external
test-only adapter serving the same fixtures over loopback HTTP; production code
and assertions are unchanged. Two real Chromium process-startup tests use a
10-second budget; deterministic timeout tests retain their existing deadlines.
