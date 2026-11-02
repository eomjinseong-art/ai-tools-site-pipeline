# 쇼츠 대본 대기열

일일 업로드(`promo_upload.yml`, 08:00 KST)는 유료 LLM을 호출하지 않습니다.
대본은 저장소에 커밋된 대기열에서 고르고, 그 도구의 대본이 없으면 카드 필드로 만든 템플릿을 씁니다.
템플릿을 써도 업로드는 실패하지 않습니다. 템플릿은 대본 id 를 소비하지 않습니다.

## 파일

| 경로 | 역할 |
| --- | --- |
| `content_queue/shorts_scripts.json` | 사전 작성 대본. 주 1회 보조자가 항목을 추가합니다. |
| `content_queue/consumed_ids.json` | 이미 YouTube 업로드에 쓴 id. |
| `out/content_queue_state.json` | 같은 소비 목록의 런타임 복사본. Actions 캐시가 커밋이 실패해도 id 가 남게 합니다. |

실제로 소비된 id 는 두 파일의 합집합입니다.

```
consumed = ids(content_queue/consumed_ids.json) ∪ ids(out/content_queue_state.json)
```

id 는 업로드가 성공한 뒤에만 기록합니다. `--dry-run` 과 `--skip-upload` 는 기록하지 않습니다.

## 스키마

`shorts_scripts.json`:

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `version` | 예 | 현재 `1` |
| `cadence_per_day` | 예 | 하루에 소비하는 편수. 이 저장소는 `1` |
| `scripts[].id` | 예 | 고유 문자열. 재사용하지 않습니다. |
| `scripts[].tool_name` | 예 | 도구 이름. 제목/훅/이름과 비교합니다. |
| `scripts[].aliases` | 아니오 | 추가 매칭 문자열. `AI`, `툴` 처럼 짧은 일반어는 무시됩니다. |
| `scripts[].match_ids` | 아니오 | 수집기 영상 id 또는 도구 id 가 같으면 매칭합니다. |
| `scripts[].link` | 아니오 | 설명란에 넣는 공개 URL. 카드 문장에는 넣지 않습니다. |
| `scripts[].cards` | 예 | `card1_hook`, `card2`, `card3`, `card4`, `card5_takeaway` |

카드 규칙 (`rewrite_for_shorts.py`):

- 길이 `MIN_CHARS` 이상, `VALIDATE_MAX_CHARS` 이하 (10자 이상, 55자 이하. 권장 상한은 35자)
- `http://`, `https://`, `#`, `@` 금지

`tool_name`, `aliases`, `match_ids` 가 모두 비어 있거나 카드가 규칙을 어기면 그 항목은 건너뜁니다. 일수는 세지 않고, 업로드는 템플릿으로 계속됩니다.

`consumed_ids.json`:

```json
{
  "consumed_ids": ["chatgpt-handoff"]
}
```

## 예시

아래 객체는 설명용입니다. `shorts_scripts.json` 에 들어 있지 않습니다.

```json
{
  "id": "example-tool-001",
  "tool_name": "예시도구",
  "aliases": ["예시 도구"],
  "match_ids": ["tool_example_001"],
  "link": "https://example.com/tool",
  "cards": {
    "card1_hook": "예시도구로 반복 작업을 줄이세요",
    "card2": "목적은 한 줄만 적어도 됩니다",
    "card3": "초안은 같은 틀로 고정하세요",
    "card4": "숫자는 직접 한 번 확인하세요",
    "card5_takeaway": "설명란 링크에서 바로 열어 보세요"
  }
}
```

수집기 영상의 제목, 훅, 도구 이름, id 안에 `예시도구` 또는 `예시 도구` 가 있고 이 id 가 아직 소비되지 않았으면 그날 쇼츠는 이 다섯 장을 씁니다.

## 도구에 대본이 없을 때

템플릿은 항상 같은 입력에서 같은 다섯 장을 만듭니다.

| 카드 | 필드 |
| --- | --- |
| `card1_hook` | 이름 (`tool_name`, `name`, 없으면 영상 제목, 없으면 훅) |
| `card2` | 한 줄 설명 (`one_line`, `description`, 없으면 훅, 없으면 takeaway) |
| `card3` | 핵심 기능 1 (`key_features` / `features`, 없으면 `summary_points[0]`) |
| `card4` | 핵심 기능 2 (없으면 확인 안내 문장) |
| `card5_takeaway` | 링크 CTA. URL 은 빼고 호스트 또는 "설명란 링크"만 카드에 적습니다. |

세 번째 이후 기능은 템플릿 카드에 넣지 않습니다. 필요하면 사전 대본에 적습니다.
필드가 비어 있어도 고정 문장으로 채워 업로드가 멈추지 않습니다.

## days_left

하루 한 편이면, 남은 사전 대본 수가 곧 남은 일수입니다.

```
unused_valid_scripts
  = 대기열 안에서
    - id 가 consumed 합집합에 없고
    - id 가 처음 나온 한 번만 세며
    - 카드 다섯 장이 규칙을 통과하고
    - tool_name / aliases / match_ids 중 하나라도 있는 항목

days_left = floor(unused_valid_scripts / cadence_per_day)
```

`cadence_per_day` 가 없거나 1 미만이면 1로 계산합니다.
코드는 `content_queue.compute_days_left` 입니다.

예시:

| unused_valid_scripts | cadence_per_day | days_left | 이슈 |
| --- | --- | --- | --- |
| 20 | 1 | 20 | 열지 않음 |
| 14 | 1 | 14 | 열지 않음 (14 미만이 아님) |
| 13 | 1 | 13 | `쇼츠 대본 대기열 부족` 을 열거나 본문을 갱신 |
| 27 | 2 | 13 | 같은 이슈 |

현재 저장소의 일수:

```bash
python -m content_queue status
```

`days_left` 가 출력됩니다. 소비 파일이 비어 있고 `cadence_per_day` 가 1이면 `days_left` 는 유효 대본 수와 같습니다.

## 14일 미만

매일 잡이 `days_left < 14` 이면 GitHub 이슈 **쇼츠 대본 대기열 부족** 을 엽니다.
같은 제목의 열린 이슈가 있으면 새로 만들지 않고 본문을 갱신합니다.
본문의 `days_left` 가 바뀔 때만 댓글을 추가합니다.
다시 14 이상이 되면 그 이슈를 닫습니다.

이 이슈는 업로드를 막지 않습니다. 대본이 없는 도구는 템플릿으로 올라갑니다.

## 주간 보충

1. `content_queue/shorts_scripts.json` 의 `scripts` 끝에 객체를 추가합니다.
2. `id` 는 기존과 겹치지 않게 합니다.
3. 카드 다섯 장을 규칙에 맞게 적고, `tool_name` 과 영상 제목에 나올 별칭을 넣습니다.
4. `consumed_ids` 는 지우지 않습니다. 이미 쓴 대본을 다시 쓰려면 커밋된 목록과 `out/content_queue_state.json`, Actions 캐시에서 그 id 를 함께 빼야 합니다.
5. `python -m content_queue status` 로 `days_left` 를 확인합니다.

## YouTube 로그인

업로드 단계의 refresh token 이 `invalid_grant` 이면 워크플로는 이슈 **유튜브 로그인 다시 필요** 를 열거나 본문을 갱신하고, 그 실행은 실패로 끝냅니다.
시크릿 값은 이슈에 적지 않습니다. `YT_REFRESH_TOKEN` 을 다시 발급하면 됩니다.
