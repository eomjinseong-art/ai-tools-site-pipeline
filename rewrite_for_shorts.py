def _simple_rewrite_fallback(hook: str, summary_points: List[str], takeaway: str) -> Dict[str, str]:
    """
    Anthropic 호출이 불가능할 때 사용하는 간단한 규칙 기반 폴백 리라이팅.
    - 길이 제한 적용(권장 15~30자 범위로 트리밍)
    - 최소한의 표현 변경(불필요 공백 제거, 문장 끝 마침표 제거, 일부 교체)
    """
    def normalize(s: str, max_len: int = 28) -> str:
        s = s.strip()
        s = re.sub(r"\s+", " ", s)
        # 마침표/느낌표/물음표 끝 제거
        s = re.sub(r"[。.!?]+$", "", s)
        if len(s) > max_len:
            # 잘라낼 때 자연스럽게 끝나도록 마지막 공백 위치에서 자름
            cut = s[:max_len].rfind(" ")
            if cut > max_len // 2:
                s = s[:cut]
            else:
                s = s[:max_len]
            s = s.rstrip(" ,;:")  # 끝에 쉼표 같은 거 없애기
            s += "…"
        return s

    card1 = normalize(hook, max_len=30)
    card2 = normalize(summary_points[0], max_len=28)
    card3 = normalize(summary_points[1], max_len=28)
    card4 = normalize(summary_points[2], max_len=28)
    card5 = normalize(takeaway, max_len=34)

    return {
        "card1_hook": card1,
        "card2": card2,
        "card3": card3,
        "card4": card4,
        "card5_takeaway": card5,
    }


def rewrite_summary_for_shorts(hook: str, summary_points: List[str], takeaway: str,
                               model: Optional[str] = None,
                               max_retries: int = MAX_RETRIES) -> Dict[str, str]:
    """
    Anthropic 호출을 시도하되, 결제/서비스 오류 등으로 실패하면 간단한 폴백을 사용.
    """
    if anthropic is None:
        # SDK가 없으면 폴백
        return _simple_rewrite_fallback(hook, summary_points, takeaway)

    if not ANTHROPIC_API_KEY:
        # 키가 없으면 폴백
        return _simple_rewrite_fallback(hook, summary_points, takeaway)

    if len(summary_points) < 3:
        raise RewriteError("summary_points는 최소 3개 필요합니다.")

    model = model or REWRITE_MODEL

    prompt = PROMPT_TEMPLATE.format(
        min_chars=MIN_CHARS,
        max_chars=MAX_CHARS,
        hook=hook,
        p1=summary_points[0],
        p2=summary_points[1],
        p3=summary_points[2],
        takeaway=takeaway,
    )

    client = anthropic.Client(api_key=ANTHROPIC_API_KEY)

    attempt = 0
    last_exc = None
    while attempt < max_retries:
        try:
            attempt += 1
            # 단순화된 요청 (temperature 제거 등 SDK 호환성 고려)
            resp = client.messages.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )

            raw = getattr(resp, 'content', None)
            if raw and isinstance(raw, list) and len(raw) > 0:
                raw_text = raw[0].text
            else:
                raw_text = str(resp)

            cleaned = _clean_model_text(raw_text)

            # JSON 로드
            try:
                data = json.loads(cleaned)
            except Exception:
                m = re.search(r"(\{(?:[^{}]|(?R))*\})", raw_text, flags=re.DOTALL)
                if m:
                    data = json.loads(m.group(1))
                else:
                    raise

            # 필수 키 검증
            expected_keys = ["card1_hook", "card2", "card3", "card4", "card5_takeaway"]
            if not all(k in data for k in expected_keys):
                raise RewriteError(f"모델 응답에 예상 키가 없습니다: {list(data.keys())}")

            # 각 카드 검증 및 길이 조정/후처리
            for k in expected_keys:
                v = data[k].strip()
                v = re.sub(r"\s+", " ", v)
                data[k] = v
                if not _validate_card_text(v):
                    raise RewriteError(f"카드 텍스트가 유효하지 않습니다: {k} -> '{v[:40]}' (len={len(v)})")

            return data

        except Exception as e:
            last_exc = e
            # Anthropic 잔액/권한 오류인 경우 즉시 폴백으로 전환
            msg = str(e).lower()
            if "credit" in msg or "balance" in msg or "payment" in msg or "insufficient" in msg:
                # 로그 메시지를 남기고 폴백 리턴
                print("[rewrite] Anthropic 호출 실패(잔액/결제): 폴백 리라이팅 사용")
                return _simple_rewrite_fallback(hook, summary_points, takeaway)

            # SDK나 네트워크 일시 오류는 재시도
            attempt += 0  # (for clarity)
            wait = RETRY_BACKOFF ** attempt
            time.sleep(wait)
            continue

    # 모든 재시도 실패하면 폴백을 사용
    print("[rewrite] 모든 재시도 실패: 폴백 리라이팅 사용 (last_exc=", last_exc, ")")
    return _simple_rewrite_fallback(hook, summary_points, takeaway)
