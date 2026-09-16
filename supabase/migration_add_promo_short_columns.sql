-- One-time migration for the collector Supabase project
-- (sibling repo: eomjinseong-art/C-ai-tools-collector).
-- Run in the Supabase SQL editor. Safe to re-run.
--
-- These columns record that a published video was already turned
-- into a Nadoo AI promo Short, so the daily job will not pick it again.

alter table videos
  add column if not exists promo_short_youtube_id text;

alter table videos
  add column if not exists promo_short_uploaded_at timestamptz;

create index if not exists idx_videos_promo_short_pending
  on videos (published_at)
  where status = 'published' and promo_short_youtube_id is null;
