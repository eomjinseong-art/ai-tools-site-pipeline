# 레거시 검정 카드 쇼츠 중단

일일 공개 업로드로 나가던 검정 배경·흰 글자 쇼츠를 코드에서 끊었다. GitHub 화면에서 워크플로만 끄거나 공개 범위를 바꾸는 방식이 아니다. 베이지/파스텔 9장 캐러셀은 다른 파이프라인이며 이 저장소에 없고, 이 변경으로 끄거나 검정 디자인으로 바꾸지 않는다.

## 확인한 원인

저장소 코드, 워크플로 정의, Actions 실행 기록, 실행 아티팩트의 `upload.json` / `cards.json` / `source_video.json`으로 확인했다. YouTube 자격 증명은 읽지 않았다.

| 항목 | 확인 값 |
| --- | --- |
| 업로더 | `eomjinseong-art/ai-tools-site-pipeline` 의 `Promo Shorts - Daily Publish` |
| 워크플로 id | `341500131` (`.github/workflows/promo_upload.yml`) |
| 조사 시점 상태 | `disabled_manually`, `updated_at` `2026-11-05T09:23:49Z` (한국시간 11월 5일 18:23) |
| 마지막 실행 | run 85, Actions run `41958687664`, `schedule`, `2026-11-05T02:59:14Z` (한국시간 11:59), 성공, YouTube id `HYgjySdb7ts` |
| 다른 워크플로 | `CI` id `404144099`. `pull_request`에서 단위 테스트만 실행. 업로드하지 않음. 활성 유지 |

화면 형식은 이 저장소 안에서 베이지 디자인에서 바뀐 것이 아니다. `full_orchestrator.make_card_image`는 파일이 들어온 커밋 `1b72fcf` (2026-08-25)부터 배경 `(18, 18, 18)`, 흰 글자, 빨간 강조선, 하단 워터마크 `나두 AI 요약`이다. `youtube_upload.build_video_resource`는 `YT_PRIVACY_STATUS`가 없으면 `public`으로 올렸다. 채널에 승인된 베이지/파스텔 9장 캐러셀과 다른 공개 쇼츠가 매일 추가된 이유가 이 경로다.

반복처럼 보인 이유는 같은 영상 id를 매일 다시 올린 것이 아니다. 샘플 실행(run 78–85)은 Supabase `promo_short_youtube_id` 갱신이 `db_updated: true`였다.

- 수집기는 `published_at`이 오래된 순으로, 아직 쇼츠 id가 없는 영상을 고른다. run 78–83 원본은 타입캐스트/Typecast 사용법 영상이 연속이었고, run 84는 피그마/Figma 기초 강의였다.
- `content_queue/shorts_scripts.json`에는 타입캐스트와 피그마 대본이 없다. 로컬 대기열로 바꾼 커밋 `013a29b` 이후(run 83–84)는 `template_cards`가 제목·훅·요약을 카드에 그대로 옮겼다. 코드와 문서가 그 템플릿으로도 업로드를 계속하게 되어 있었다.
- run 85는 제목에 `뤼튼`이 있어 대기열 대본 `wrtn-korean`(한국어 초안)을 붙였다. 원본 영상은 이미지 생성 사용법이다. 부분 문자열 매칭과, 수집기 백로그와 맞지 않는 고정 대본 풀이 겹친 결과다. 템플릿 경로는 script id를 소비하지 않아 비슷한 카드가 다음 날도 나온다.
- Actions 캐시의 `out/promo_shorts_state.json`은 아티팩트 기준으로 전체 이력이 아니라 직전 한두 건만 남았다. DB 컬럼이 없으면 중복 방지로 충분하지 않다. 이번 샘플에서는 DB 갱신이 되어 같은 행의 재업로드는 막혔다.

## 다시 켜질 수 있던 경로

UI에서 워크플로를 꺼 둔 상태여도 `main`에는 다음이 남아 있었다.

- `on.schedule` 크론 `0 23 * * *`와 `workflow_dispatch`. 수동 실행 기록이 11회 있다. 워크플로를 다시 활성화하면 일정과 수동 실행이 돌아온다.
- `python promo_pipeline.py`는 플래그 없이 렌더 후 공개 업로드했다.
- `--skip-upload`와 `python full_orchestrator.py`는 검정 카드를 계속 그렸다.
- `youtube_upload.upload_shorts`와 공개 프라이버시 기본값.
- `deploy_to_repo.ps1`는 워크플로를 다른 체크아웃에 복사하고 `git push`했다.

`rewrite_driver.py`는 대본과 TTS만 하고 영상을 만들거나 올리지 않는다. `CI`는 테스트를 실행할 뿐 업로드하지 않는다. 다른 브랜치나 다른 워크플로 파일은 없었다.

## 지금 막는 방법

- `legacy_shorts_retirement.refuse_legacy_black_card_shorts`가 검정 카드 생성(`make_card_image`, `orchestrate`)과 YouTube 업로드(`upload_shorts`, `build_video_resource`)에서 예외를 낸다. 자격 증명을 읽기 전에 멈춘다.
- `python promo_pipeline.py`에서 `--dry-run`이 아니면 종료 코드 2와 `out/retired.json`만 남긴다. 수집기 조회, 렌더, 업로드, 대본 id 소비를 하지 않는다. `--skip-upload`도 생성이므로 거부한다.
- `YT_PRIVACY_STATUS`를 비롯한 환경 변수로 다시 켜지지 않는다. 공개 업로드 기본값을 두지 않는다.
- 워크플로 파일 경로와 이름 `Promo Shorts - Daily Publish`는 유지한다. 일정은 없다. 수동 실행은 이유를 출력하고 실패한다. 시크릿을 넘기지 않는다.
- `deploy_to_repo.ps1`는 복사와 push 없이 즉시 실패한다.

`--dry-run`, `python -m content_queue status`, 수집기 행 판별, 이슈 문구 도우미, `CI`의 단위 테스트는 영상을 만들지 않으므로 유지한다.

## 다시 사용하려면

명시적인 새 디자인 승인과 그 승인을 반영한 새 코드 변경이 필요하다. 워크플로를 다시 활성화하거나, 환경 변수를 넣거나, 프라이버시만 `unlisted`로 바꾸는 것으로는 켜지지 않는다. 베이지/파스텔 캐러셀을 이 검정 카드 경로에 연결하지 않는다.

## 남은 위험

- GitHub에 둔 YouTube 시크릿은 읽거나 지우거나 회전하지 않았다. 이 커밋 이전의 체크아웃이나, 비활성화가 풀린 옛 커밋의 워크플로는 아직 업로드할 수 있다.
- 이미 공개된 영상은 여기서 삭제하거나 비공개로 바꾸지 않는다.
- 이 저장소 밖의 사본이 옛 스크립트를 실행하면 이 PR만으로 멈추지 않는다. 그 사본이 이 코드를 쓰기 전까지 남는다.
- 이 PR을 되돌리거나 워크플로 파일에 일정을 다시 넣고 워크플로를 활성화하면 게시가 돌아온다.
