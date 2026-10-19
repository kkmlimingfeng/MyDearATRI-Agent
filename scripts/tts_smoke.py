"""Exercise the local Qwen3-TTS API without starting the frontend."""

from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="你好，早上好。今天也请多指教。")
    parser.add_argument("--reference", default="atri")
    parser.add_argument("--ref-text", default=None)
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--model", choices=("qwen3-0.6b-q8", "qwen3-1.7b-q4"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", type=Path, default=Path("Qwen/tts-smoke.wav"))
    args = parser.parse_args()

    payload_data = {
        "text": args.text,
        "reference": args.reference,
        "language": args.language,
        "response_format": "pcm",
    }
    if args.ref_text is not None:
        payload_data["ref_text"] = args.ref_text
    if args.model is not None:
        payload_data["model"] = args.model
    payload = json.dumps(payload_data, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"http://127.0.0.1:{args.port}/api/tts/speech",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    opener = build_opener(ProxyHandler({}))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    first_audio = None
    total_bytes = 0
    with opener.open(request, timeout=300) as response, wave.open(str(args.output), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        while chunk := response.read(4096):
            if first_audio is None:
                first_audio = time.monotonic() - started
            output.writeframesraw(chunk)
            total_bytes += len(chunk)
    elapsed = time.monotonic() - started
    print(f"first_audio={first_audio:.2f}s total={elapsed:.2f}s audio={total_bytes / 48_000:.2f}s output={args.output}")


if __name__ == "__main__":
    main()
