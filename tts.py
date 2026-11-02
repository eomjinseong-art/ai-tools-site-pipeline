"""
무료 한국어 TTS.

1. edge-tts (기본 음성 ko-KR-SunHiNeural, 실패 시 지수 백오프 재시도)
2. 그래도 실패하면 gTTS (lang=ko)

유료 TTS 키는 쓰지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "ko-KR-SunHiNeural"
ALTERNATE_VOICE = "ko-KR-InJoonNeural"
EDGE_TTS_VERSION = "7.3.1"
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0
MIN_AUDIO_BYTES = 64


class TtsError(Exception):
    pass


def resolve_voice(explicit: Optional[str] = None) -> str:
    voice = (explicit or os.environ.get("EDGE_TTS_VOICE") or DEFAULT_VOICE).strip()
    return voice or DEFAULT_VOICE


def _backoff_seconds(failed_attempts: int) -> float:
    if failed_attempts < 1:
        return 0.0
    return BACKOFF_BASE_SECONDS * (2 ** (failed_attempts - 1))


def _file_ok(path: str) -> bool:
    file_path = Path(path)
    return file_path.is_file() and file_path.stat().st_size >= MIN_AUDIO_BYTES


def _ffmpeg_to_wav(src_mp3: str, dest_wav: str) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        src_mp3,
        "-ar",
        "22050",
        "-ac",
        "2",
        dest_wav,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not _file_ok(dest_wav):
        detail = (result.stderr or result.stdout or "").strip()
        raise TtsError(f"ffmpeg wav 변환 실패: {detail[:300]}")


def _place_audio(mp3_path: str, out_path: str) -> None:
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".mp3":
        if Path(mp3_path).resolve() != destination.resolve():
            destination.write_bytes(Path(mp3_path).read_bytes())
        if not _file_ok(str(destination)):
            raise TtsError(f"TTS 파일이 너무 작습니다: {destination}")
        return
    _ffmpeg_to_wav(mp3_path, str(destination))


def _edge_save(text: str, voice: str, mp3_path: str) -> None:
    import edge_tts

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(mp3_path)

    asyncio.run(_run())
    if not _file_ok(mp3_path):
        raise TtsError("edge-tts 가 오디오를 쓰지 못했습니다.")


def _gtts_save(text: str, mp3_path: str) -> None:
    from gtts import gTTS

    gTTS(text, lang="ko", lang_check=False).save(mp3_path)
    if not _file_ok(mp3_path):
        raise TtsError("gTTS 가 오디오를 쓰지 못했습니다.")


def synthesize_speech(
    text: str,
    out_path: str,
    *,
    voice: Optional[str] = None,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = MAX_ATTEMPTS,
    edge_save: Callable[[str, str, str], None] = _edge_save,
    gtts_save: Callable[[str, str], None] = _gtts_save,
) -> str:
    """
    out_path 에 음성을 저장하고 사용한 엔진 이름(edge-tts 또는 gtts)을 반환한다.
    wav 경로면 mp3 를 ffmpeg 로 변환한다.
    """
    spoken = (text or "").strip()
    if not spoken:
        raise TtsError("TTS 텍스트가 비어 있습니다.")
    chosen_voice = resolve_voice(voice)
    attempts = max_attempts if max_attempts >= 1 else 1
    last_error: Optional[BaseException] = None

    for attempt in range(1, attempts + 1):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            mp3_path = handle.name
        try:
            edge_save(spoken, chosen_voice, mp3_path)
            _place_audio(mp3_path, out_path)
            logger.info("TTS edge-tts voice=%s path=%s", chosen_voice, out_path)
            return "edge-tts"
        except Exception as exc:
            last_error = exc
            logger.warning("edge-tts attempt %s/%s failed: %s", attempt, attempts, exc)
            if attempt < attempts:
                delay = _backoff_seconds(attempt)
                if delay > 0:
                    sleep(delay)
        finally:
            try:
                os.remove(mp3_path)
            except OSError:
                pass

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
        mp3_path = handle.name
    try:
        gtts_save(spoken, mp3_path)
        _place_audio(mp3_path, out_path)
        logger.info("TTS fallback gTTS path=%s (edge last error=%s)", out_path, last_error)
        return "gtts"
    except Exception as exc:
        raise TtsError(f"edge-tts 와 gTTS 가 모두 실패했습니다: edge={last_error}; gtts={exc}") from exc
    finally:
        try:
            os.remove(mp3_path)
        except OSError:
            pass
