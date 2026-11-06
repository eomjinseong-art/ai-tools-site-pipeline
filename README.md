# Nadoo AI (AI Tools Korea) Shorts pipeline

The legacy black-card YouTube Shorts publisher is retired. It drew generic black/white cards watermarked `나두 AI 요약` and uploaded them as public Shorts. That path now fails closed.

`python promo_pipeline.py` without `--dry-run` exits 2, writes `out/retired.json`, and does not read the collector, render, or upload. No environment variable or privacy flag turns it back on. Reactivation requires an explicit new design permission and a new code change.

Cause, the paths that could start it again, and the remaining risks: [docs/LEGACY_BLACK_CARD_SHORTS_RETIREMENT.md](docs/LEGACY_BLACK_CARD_SHORTS_RETIREMENT.md).

The beige/pastel 9-card carousel is a separate pipeline. It is not in this repository, and this change does not disable it or restyle it as black cards.

## What still runs

| Command or workflow | Behavior |
| --- | --- |
| `python -m content_queue status` | Prints the prewritten script ledger. No video. |
| `python promo_pipeline.py --dry-run --input tests/fixtures/sample_video.json` | Resolves a script to JSON. No TTS, render, or upload. |
| `supabase_source.py` helpers | Read and filter collector rows. They do not upload. |
| `.github/workflows/ci.yml` | Unit tests on pull requests. |

Script fields and the days-left formula: [docs/CONTENT_QUEUE.md](docs/CONTENT_QUEUE.md).

`.github/workflows/promo_upload.yml` keeps the name `Promo Shorts - Daily Publish` so the existing disabled workflow stays that workflow. It has no schedule. A manual run fails with the retirement reason and does not upload. Do not re-enable it.

`deploy_to_repo.ps1` no longer copies or pushes the publisher.

## Secrets

This retirement does not read, print, rotate, or delete YouTube or Supabase secrets. An old checkout can still upload until it runs this code. Do not commit token files, client secrets, or `.env`.

## One-time Supabase migration

Historical promo rows used the collector `videos` table. The retired publisher does not write these columns. The SQL remains for the existing schema:

```sql
alter table videos
  add column if not exists promo_short_youtube_id text;

alter table videos
  add column if not exists promo_short_uploaded_at timestamptz;

create index if not exists idx_videos_promo_short_pending
  on videos (published_at)
  where status = 'published' and promo_short_youtube_id is null;
```

The same statements are in `supabase/migration_add_promo_short_columns.sql`.

## Local checks

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m content_queue status
python promo_pipeline.py --input tests/fixtures/sample_video.json --dry-run
```
