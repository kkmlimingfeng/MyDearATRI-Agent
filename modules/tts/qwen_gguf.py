"""Local Qwen3-TTS GGUF service and ATRI reference audio handling."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import threading
import time
import wave
from array import array
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = ROOT / "data" / "atri" / "voice"
RUNTIME_DIR = ROOT / "Qwen" / "qwentts.cpp"
MODEL_DIR = ROOT / "models" / "TTS"
DEFAULT_REFERENCE = "atri"
DEFAULT_TTS_URL = "http://127.0.0.1:8767"
PRESET_FILES = ("阿里嘎多.wav", "请多指教.wav", "早上好.wav")
REFERENCE_TEXTS = {
    "阿里嘎多.wav": "ありがとう。",
    "请多指教.wav": "よろしくお願いします。",
    "早上好.wav": "おはようございます。",
}
PRESET_TEXT = "".join(REFERENCE_TEXTS[name] for name in PRESET_FILES)
SAMPLE_RATE = 24_000
MODELS = {
    "qwen3-0.6b-q8": ("qwen-talker-0.6b-base-Q8_0.gguf", "qwen-tokenizer-12hz-Q8_0.gguf"),
    "qwen3-1.7b-q4": ("qwen-talker-1.7b-base-Q4_K_M.gguf", "qwen-tokenizer-12hz-Q4_K_M.gguf"),
}
DEFAULT_MODEL = "qwen3-0.6b-q8"


class TTSRuntimeError(RuntimeError):
    pass


class QwenGGUFTTS:
    def __init__(self) -> None:
        self.url = os.environ.get("ATRI_TTS_URL", DEFAULT_TTS_URL).rstrip("/")
        self._url_parts = urlsplit(self.url)
        self._local_port = self._url_parts.port
        self._can_start_local = (
            self._url_parts.scheme == "http"
            and self._url_parts.hostname == "127.0.0.1"
            and self._local_port is not None
            and self._url_parts.path in {"", "/"}
            and not self._url_parts.query
            and not self._url_parts.fragment
        )
        self.device = os.environ.get("ATRI_TTS_DEVICE", "CUDA0")
        self.binary = Path(os.environ.get("ATRI_TTS_BINARY", RUNTIME_DIR / "build-cuda" / "tts-server"))
        self.model = os.environ.get("ATRI_TTS_MODEL", DEFAULT_MODEL)
        if self.model not in MODELS:
            raise ValueError(f"Unsupported TTS model: {self.model}")
        self._opener = build_opener(ProxyHandler({}))
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._log = None
        self._registered: set[str] = set()

    def _model_paths(self, model: str) -> tuple[Path, Path]:
        talker, codec = MODELS[model]
        return (Path(os.environ.get("ATRI_TTS_TALKER", MODEL_DIR / talker)),
                Path(os.environ.get("ATRI_TTS_CODEC", MODEL_DIR / codec)))

    def models(self) -> dict:
        return {"selected": self.model, "models": [
            {"id": name, "available": all(path.is_file() for path in self._model_paths(name))}
            for name in MODELS
        ]}

    def _request(self, path: str, payload: dict | None = None, timeout: float = 15):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            self.url + path,
            data=body,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            return self._opener.open(request, timeout=timeout)
        except HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            raise TTSRuntimeError(f"Qwen TTS returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise TTSRuntimeError(f"Qwen TTS is unavailable: {exc.reason}") from exc

    def _healthy(self) -> bool:
        try:
            with self._request("/v1/models", timeout=1) as response:
                models = json.load(response).get("data", [])
                return any(item.get("id") == self.model for item in models)
        except (TTSRuntimeError, TimeoutError, ValueError, KeyError):
            return False

    def status(self) -> dict:
        talker, codec = self._model_paths(self.model)
        return {
            "ready": self._healthy(),
            "selected": self.model,
            "models": self.models()["models"],
            "device": self.device,
            "sample_rate": SAMPLE_RATE,
            "binary_found": self.binary.is_file(),
            "talker_found": talker.is_file(),
            "codec_found": codec.is_file(),
            "default_reference": DEFAULT_REFERENCE,
        }

    def select_model(self, model: str) -> dict:
        if model not in MODELS:
            raise ValueError(f"Unsupported TTS model: {model}")
        with self._lock:
            talker, codec = self._model_paths(model)
            if not talker.is_file() or not codec.is_file():
                raise TTSRuntimeError(f"Model files are missing for {model}")
            if model != self.model:
                self.close()
                self.model = model
                self._registered.clear()
            return self.status()

    def ensure_started(self) -> None:
        with self._lock:
            if self._healthy():
                return
            if self._process is None or self._process.poll() is not None:
                talker, codec = self._model_paths(self.model)
                for label, path in (("runtime", self.binary), ("talker GGUF", talker), ("codec GGUF", codec)):
                    if not path.is_file():
                        raise TTSRuntimeError(f"Missing {label}: {path}")
                if not self._can_start_local:
                    raise TTSRuntimeError(f"Start the configured Qwen TTS service at {self.url}")
                try:
                    with self._request("/health", timeout=1):
                        raise TTSRuntimeError("A different TTS model is already running at the configured URL")
                except TTSRuntimeError as exc:
                    if "different TTS model" in str(exc):
                        raise
                log_path = RUNTIME_DIR / "tts-server.log"
                self._log = log_path.open("ab")
                environment = os.environ.copy()
                conda_prefix = environment.get("CONDA_PREFIX")
                if conda_prefix:
                    library_dir = str(Path(conda_prefix) / "lib")
                    environment["LD_LIBRARY_PATH"] = ":".join(
                        part for part in (library_dir, environment.get("LD_LIBRARY_PATH", "")) if part
                    )
                self._process = subprocess.Popen(
                    [str(self.binary), "--model", str(talker), "--codec", str(codec),
                     "--device", self.device, "--host", "127.0.0.1", "--port", str(self._local_port),
                     "--alias", self.model],
                    cwd=ROOT,
                    env=environment,
                    stdout=self._log,
                    stderr=subprocess.STDOUT,
                )
                self._registered.clear()
            for _ in range(120):
                if self._healthy():
                    return
                if self._process.poll() is not None:
                    raise TTSRuntimeError(f"Qwen TTS exited during startup; see {RUNTIME_DIR / 'tts-server.log'}")
                time.sleep(0.5)
            raise TTSRuntimeError("Qwen TTS did not become ready within 60 seconds")

    def close(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
            if self._log is not None:
                self._log.close()
                self._log = None
            self._registered.clear()

    def references(self) -> list[dict]:
        result = []
        if all((REFERENCE_DIR / name).is_file() for name in PRESET_FILES):
            result.append({"id": DEFAULT_REFERENCE, "files": list(PRESET_FILES),
                           "label": "ATRI (三段组合)", "ref_text": PRESET_TEXT})
        for path in sorted(REFERENCE_DIR.glob("*.wav")):
            try:
                with wave.open(str(path), "rb") as audio:
                    duration = round(audio.getnframes() / audio.getframerate(), 2)
            except (OSError, wave.Error):
                continue
            result.append({
                "id": path.name,
                "label": path.stem,
                "duration_seconds": duration,
                "ref_text": REFERENCE_TEXTS.get(path.name),
            })
        return result

    def _reference_audio(self, reference: str) -> tuple[bytes, str]:
        if reference == DEFAULT_REFERENCE:
            files = [REFERENCE_DIR / name for name in PRESET_FILES]
            if not all(path.is_file() for path in files):
                raise ValueError("ATRI reference preset is incomplete")
            samples = array("h")
            sample_rate = None
            for index, path in enumerate(files):
                with wave.open(str(path), "rb") as audio:
                    if audio.getsampwidth() != 2 or audio.getnchannels() not in (1, 2):
                        raise ValueError(f"Unsupported WAV format: {path.name}")
                    if sample_rate is None:
                        sample_rate = audio.getframerate()
                    elif audio.getframerate() != sample_rate:
                        raise ValueError("ATRI reference clips must have the same sample rate")
                    clip = array("h")
                    clip.frombytes(audio.readframes(audio.getnframes()))
                    if audio.getnchannels() == 2:
                        clip = array("h", ((clip[i] + clip[i + 1]) // 2 for i in range(0, len(clip), 2)))
                    if index:
                        samples.extend([0] * int(sample_rate * 0.12))
                    samples.extend(clip)
            output = io.BytesIO()
            with wave.open(output, "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(sample_rate)
                audio.writeframes(samples.tobytes())
            stamp = ":".join(str(path.stat().st_mtime_ns) for path in files)
            return output.getvalue(), stamp

        if not isinstance(reference, str) or Path(reference).name != reference or not reference.endswith(".wav"):
            raise ValueError("Invalid reference audio name")
        path = REFERENCE_DIR / reference
        if not path.is_file():
            raise ValueError(f"Reference audio not found: {reference}")
        return path.read_bytes(), str(path.stat().st_mtime_ns)

    def _voice_name(self, reference: str, stamp: str, ref_text: str) -> str:
        key = f"{reference}\0{stamp}\0{ref_text}".encode("utf-8")
        return "atri-" + hashlib.sha256(key).hexdigest()[:16]

    def _ensure_voice(self, reference: str, ref_text: str) -> str:
        audio, stamp = self._reference_audio(reference)
        name = self._voice_name(reference, stamp, ref_text)
        with self._lock:
            if name in self._registered:
                return name
            with self._request("/v1/audio/voices", {
                "name": name,
                "ref_text": ref_text,
                "wav_b64": base64.b64encode(audio).decode("ascii"),
            }, timeout=60) as response:
                response.read()
            self._registered.add(name)
        return name

    @contextmanager
    def speech(self, text: str, reference: str = DEFAULT_REFERENCE, ref_text: str | None = None,
               language: str = "Chinese", response_format: str = "pcm", model: str | None = None):
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise ValueError("Text must contain 1 to 1000 characters")
        if ref_text is None:
            ref_text = ""
        if not isinstance(ref_text, str) or len(ref_text) > 1000:
            raise ValueError("Invalid reference transcript")
        if language not in {"Chinese", "Japanese", "English", "auto"}:
            raise ValueError("Unsupported target language")
        if response_format not in {"pcm", "wav"}:
            raise ValueError("response_format must be pcm or wav")
        with self._lock:
            if model is not None:
                self.select_model(model)
            self.ensure_started()
            voice = self._ensure_voice(reference, ref_text)
            # Qwen emits 12.5 audio frames per second; bound malformed or looping output.
            max_new_tokens = min(375, max(63, 25 + len(text.strip()) * 5))
            with self._request("/v1/audio/speech", {
                "model": self.model,
                "input": text.strip(),
                "voice": voice,
                "language": language,
                "response_format": response_format,
                "max_new_tokens": max_new_tokens,
            }, timeout=180) as response:
                yield response


tts = QwenGGUFTTS()
