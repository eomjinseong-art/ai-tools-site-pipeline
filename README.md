# Nadoo AI (AI Tools Korea) Shorts pipeline

Daily GitHub Action that picks one collector video, chooses a pre-written Korean Shorts script (or a deterministic template), renders a vertical Short with free TTS, and uploads it to YouTube.

Production entrypoint: `python promo_pipeline.py`  
`rewrite_driver.py` is local debug only and must not be used in Actions.

Scripts and the days-left formula: [docs/CONTENT_QUEUE.md](docs/CONTENT_QUEUE.md).

```bash
python -m content_queue status
```

## Required GitHub Secrets

| Secret | Purpose |
| --- | --- |
| `SUPABASE_URL` | Collector DB (`https://xxxx.supabase.co`) |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role (bypasses RLS; never expose to browsers) |
| `YT_CLIENT_ID` | YouTube OAuth installed-app client |
| `YT_CLIENT_SECRET` | YouTube OAuth client secret |
| `YT_REFRESH_TOKEN` | Long-lived refresh token (no browser in CI) |

`GITHUB_TOKEN` is provided by Actions. The job needs `issues: write` so it can open **유튜브 로그인 다시 필요** when refresh returns `invalid_grant`, and **쇼츠 대본 대기열 부족** when fewer than 14 days of pre-written scripts remain.

Optional:

| Secret or variable | Purpose |
| --- | --- |
| `EXPECTED_YOUTUBE_CHANNEL_ID` | Abort upload if the refresh token is tied to another channel |
| `EDGE_TTS_VOICE` | Korean neural voice. Default `ko-KR-SunHiNeural`. Alternate `ko-KR-InJoonNeural`. |

TTS is `edge-tts==7.3.1` with retries, then gTTS. No paid TTS or LLM key is read. Remove leftover `OPENAI_API_KEY`, `OPENAI_MODEL`, `REWRITE_MODEL`, `ELEVENLABS_API_KEY`, and `ELEVEN_VOICE_ID` secrets if they are still stored; the workflow does not use them.

Do not commit token files, client secrets, or `.env`.

## One-time Supabase migration

Content comes from the collector project's `videos` table.

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

Script ids that were already uploaded are stored in `content_queue/consumed_ids.json` (committed at the end of a successful run) and mirrored to `out/content_queue_state.json`.

## Local commands

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m content_queue status

# queue or template + render + upload (Supabase and YouTube secrets only)
python promo_pipeline.py --outdir out

# collector JSON fixture, no network upload
python promo_pipeline.py --input tests/fixtures/sample_video.json --dry-run
```

Schedule stays `0 23 * * *` (08:00 KST). The job fails if render or YouTube upload fails. An `invalid_grant` refresh also fails the run after opening or updating the re-login issue. A short queue does not fail the run; the daily upload uses the template and updates the queue issue.
