"""Exercise streamed Qwen3 1.7B text with queued Qwen3 0.6B speech, no frontend."""

from __future__ import annotations

import queue
import re
import sys
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.llm.gguf_llm import GGUFLLM
from modules.llm.base_llm import _hide_reasoning_markup
from modules.tts.qwen_gguf import tts


OUTPUT = ROOT / "Qwen" / "tts-smoke-live-stream-short-greeting-1.7b-0.6b.wav"
EMOJI_TEST_CHARS = re.compile(r"[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")


def clean_for_speech(text: str) -> str:
    return EMOJI_TEST_CHARS.sub("", text).replace("  ", " ").strip()


def split_sentences(text: str, flush: bool = False) -> tuple[list[str], str]:
    chars = list(clean_for_speech(text))
    segments = []
    start = 0
    for index, char in enumerate(chars):
        length = index - start + 1
        following = chars[index + 1] if index + 1 < len(chars) else ""
        boundary = char in "。！？!?;；\n" or (char == "." and (not following or following.isspace()))
        boundary = boundary or (length >= 56 and char in "，,、:：") or length >= 160
        if boundary:
            segment = "".join(chars[start:index + 1]).strip()
            if segment:
                segments.append(segment)
            start = index + 1
    remainder = "".join(chars[start:])
    if flush and remainder.strip():
        segments.append(remainder.strip())
        remainder = ""
    return segments, remainder


def main() -> None:
    model = ROOT / "models" / "LLM" / "Qwen3-1.7B-Q4_K_M.gguf"
    if not model.is_file():
        raise FileNotFoundError(model)

    work = queue.Queue()
    errors = []
    events = {}
    started = time.monotonic()

    def synthesize() -> None:
        try:
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(OUTPUT), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(24_000)
                while True:
                    text = work.get()
                    if text is None:
                        break
                    print(f"[tts queued at {time.monotonic() - started:.2f}s] {text}", flush=True)
                    with tts.speech(text, reference="atri", language="Chinese", response_format="pcm", model="qwen3-0.6b-q8") as response:
                        first_chunk = True
                        while chunk := response.read(4096):
                            if first_chunk:
                                events.setdefault("first_audio", time.monotonic() - started)
                                first_chunk = False
                            output.writeframesraw(chunk)
        except Exception as exc:
            errors.append(exc)

    llm = GGUFLLM(
        module_id="smoke-llm",
        bus=None,
        model_path=str(model),
        n_ctx=2048,
        n_batch=128,
        n_gpu_layers=-1,
        temperature=0.2,
        max_tokens=512,
    )
    worker = None
    try:
        print("[tts] loading qwen3-0.6b-q8 on CUDA", flush=True)
        tts.select_model("qwen3-0.6b-q8")
        tts.ensure_started()
        events["tts_ready"] = time.monotonic() - started
        llm.initialize()
        worker = threading.Thread(target=synthesize, name="tts-smoke-worker", daemon=True)
        worker.start()

        last_draft = ""
        pending = ""

        def on_progress(draft: str) -> None:
            nonlocal last_draft, pending
            if draft.startswith(last_draft):
                pending += draft[len(last_draft):]
            else:
                pending = draft
            last_draft = draft
            segments, pending = split_sentences(pending)
            for segment in segments:
                events.setdefault("first_sentence", time.monotonic() - started)
                work.put(segment)

        result = llm.generate_response_stream(
            [{"role": "user", "content": "请只回复这句话，不要扩写，也不要换说法：早上好，愿你今天心情愉快、做事顺利。😊"}],
            tools=None,
            on_progress=on_progress,
        )
        final_text = _hide_reasoning_markup(result.content or "")
        if not final_text:
            raise RuntimeError("Qwen3-1.7B returned no user-facing text")
        if final_text.startswith(last_draft):
            pending += final_text[len(last_draft):]
        else:
            pending = final_text
        on_progress(final_text)
        segments, _ = split_sentences(pending, flush=True)
        for segment in segments:
            events.setdefault("first_sentence", time.monotonic() - started)
            work.put(segment)
        events["llm_finished"] = time.monotonic() - started
        if "😊" not in final_text:
            raise RuntimeError("LLM smoke prompt did not produce the requested emoji")
        if "😊" in clean_for_speech(final_text):
            raise RuntimeError("Emoji was not removed from TTS input")
        print(f"[llm final] {final_text}", flush=True)
        print(f"[tts input] {clean_for_speech(final_text)}", flush=True)
    finally:
        if worker is not None:
            work.put(None)
            worker.join()
        llm.shutdown()
        tts.close()

    if errors:
        raise errors[0]
    if not OUTPUT.is_file() or OUTPUT.stat().st_size <= 44:
        raise RuntimeError("TTS produced no PCM audio")
    with wave.open(str(OUTPUT), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    print(f"[timing] {events}")
    print(f"[audio] {OUTPUT} duration={duration:.2f}s bytes={OUTPUT.stat().st_size}")


if __name__ == "__main__":
    main()
