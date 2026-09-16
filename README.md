# Nadoo AI (AI Tools Korea) Shorts pipeline

Daily GitHub Action that picks one collector video, rewrites five Korean cards with OpenAI, renders a vertical Short, and uploads it to YouTube.

Production entrypoint: `python promo_pipeline.py`  
`rewrite_driver.py` is local debug only and must not be used in Actions.

## Required GitHub Secrets

| Secret | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Card rewrite (Chat Completions) |
| `ELEVENLABS_API_KEY` | TTS |
| `ELEVEN_VOICE_ID` | ElevenLabs voice |
| `SUPABASE_URL` | Collector DB (`https://xxxx.supabase.co`) |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role (bypasses RLS; never expose to browsers) |
| `YT_CLIENT_ID` | YouTube OAuth installed-app client |
| `YT_CLIENT_SECRET` | YouTube OAuth client secret |
| `YT_REFRESH_TOKEN` | Long-lived refresh token (no browser in CI) |

Optional secrets:

| Secret | Purpose |
| --- | --- |
| `OPENAI_MODEL` / `REWRITE_MODEL` | Override default `gpt-4.1-mini` (claude-* values are ignored) |
| `EXPECTED_YOUTUBE_CHANNEL_ID` | Abort upload if the refresh token is tied to another channel |
| `GOOGLE_SERVICE_ACCOUNT` | Unused by this pipeline; left available if you add GCS later |

Do not commit token files, client secrets, or `.env`.

## One-time Supabase migration

Content comes from sibling repo `eomjinseong-art/C-ai-tools-collector` table `videos`.

The job selects a row where:

- `status = 'published'`
- `hook`, `summary_points` (≥3), and `takeaway` are filled
- `promo_short_youtube_id` is null (not yet posted as a promo Short)

Run this once in the Supabase SQL editor (also in `supabase/migration_add_promo_short_columns.sql`):

```sql
alter table videos
  add column if not exists promo_short_youtube_id text;

alter table videos
  add column if not exists promo_short_uploaded_at timestamptz;

create index if not exists idx_videos_promo_short_pending
  on videos (published_at)
  where status = 'published' and promo_short_youtube_id is null;
```

If the columns are missing, the job falls back to `out/promo_shorts_state.json`. That file does not survive a fresh Actions checkout unless the workflow cache restores it, so the SQL columns are the durable source of truth.

## Local commands

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v

# rewrite + render + upload (needs all secrets in the env)
python promo_pipeline.py --outdir out

# collector JSON fixture, no network upload
python promo_pipeline.py --input tests/fixtures/sample_video.json --dry-run
```

Schedule stays `0 23 * * *` (08:00 KST). The job fails if render or YouTube upload fails; wav-only artifacts are no longer treated as success.
