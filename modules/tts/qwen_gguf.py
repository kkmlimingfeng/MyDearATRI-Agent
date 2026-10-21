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
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
VOICE_DATA_DIR = ROOT / "data" / "voice"
REFERENCE_DIR = VOICE_DATA_DIR / "atri"
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
VOICE_UPLOAD_MAX_FILES = 500
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
        if not VOICE_DATA_DIR.is_dir():
            return result
        for profile_dir in sorted(VOICE_DATA_DIR.iterdir(), key=lambda path: path.name.casefold()):
            if profile_dir.is_symlink() or not profile_dir.is_dir():
                continue
            selected = self._selected_profile_files(profile_dir)
            if selected:
                duration = sum(self._wav_details(path)["duration_seconds"] for path in selected)
                label = "ATRI" if profile_dir.name == DEFAULT_REFERENCE else profile_dir.name
                result.append({
                    "id": profile_dir.name,
                    "files": [path.name for path in selected],
                    "label": f"{label} ({len(selected)}段组合)",
                    "duration_seconds": round(duration, 2),
                    "ref_text": self._profile_transcript(selected),
                })
            for path in self._profile_wavs(profile_dir):
                duration = self._wav_details(path)["duration_seconds"]
                reference_id = path.relative_to(VOICE_DATA_DIR).as_posix()
                result.append({
                    "id": reference_id,
                    "label": f"{profile_dir.name} · {path.stem}",
                    "duration_seconds": duration,
                    "ref_text": self._clip_transcript(path),
                })
        return result

    def _profile_directory(self, profile: str) -> Path | None:
        if not isinstance(profile, str) or not profile or profile in {".", ".."} or "/" in profile or "\\" in profile:
            return None
        directory = VOICE_DATA_DIR / profile
        if directory.is_symlink() or not directory.is_dir():
            return None
        try:
            directory.resolve().relative_to(VOICE_DATA_DIR.resolve())
        except ValueError:
            return None
        return directory

    def _profile_wavs(self, profile_dir: Path) -> list[Path]:
        try:
            paths = sorted(profile_dir.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            return []
        result = []
        for path in paths:
            if path.suffix.lower() != ".wav" or path.is_symlink() or not path.is_file():
                continue
            try:
                self._wav_details(path)
            except (OSError, wave.Error, ValueError, ZeroDivisionError):
                continue
            result.append(path)
        return result

    @staticmethod
    def _wav_details(path: Path) -> dict:
        with wave.open(str(path), "rb") as audio:
            sample_rate = audio.getframerate()
            if sample_rate <= 0:
                raise ValueError("Invalid WAV sample rate")
            return {
                "duration_seconds": round(audio.getnframes() / sample_rate, 2),
                "sample_rate": sample_rate,
                "channels": audio.getnchannels(),
                "sample_width": audio.getsampwidth(),
                "supported": audio.getsampwidth() == 2 and audio.getnchannels() in (1, 2),
            }

    def _selected_profile_files(self, profile_dir: Path) -> list[Path]:
        wavs = self._profile_wavs(profile_dir)
        selection_path = profile_dir / "selection.json"
        if selection_path.is_symlink() or not selection_path.is_file():
            names = [name for name in PRESET_FILES if (profile_dir / name) in wavs] if profile_dir.name == DEFAULT_REFERENCE else [path.name for path in wavs]
            return [profile_dir / name for name in names]
        try:
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            names = selection.get("files") if isinstance(selection, dict) else None
        except (OSError, json.JSONDecodeError):
            names = None
        if not isinstance(names, list):
            return []
        allowed = {path.name: path for path in wavs}
        selected = [allowed[name] for name in names if isinstance(name, str) and name in allowed]
        return list(dict.fromkeys(selected))

    def _clip_transcript(self, path: Path) -> str | None:
        transcript = REFERENCE_TEXTS.get(path.name) if path.parent.name == DEFAULT_REFERENCE else None
        transcript_path = path.with_suffix(".txt")
        if transcript_path.is_file() and not transcript_path.is_symlink():
            try:
                candidate = transcript_path.read_text(encoding="utf-8").strip()
                if candidate:
                    transcript = candidate[:1000]
            except (OSError, UnicodeDecodeError):
                pass
        return transcript

    def _profile_transcript(self, files: list[Path]) -> str:
        if files and files == [REFERENCE_DIR / name for name in PRESET_FILES]:
            return PRESET_TEXT
        transcripts = [self._clip_transcript(path) for path in files]
        if not transcripts or any(not text for text in transcripts):
            return ""
        return " ".join(transcripts)[:1000]

    def voice_profiles(self) -> list[dict]:
        profiles = []
        if not VOICE_DATA_DIR.is_dir():
            return profiles
        for profile_dir in sorted(VOICE_DATA_DIR.iterdir(), key=lambda path: path.name.casefold()):
            if profile_dir.is_symlink() or not profile_dir.is_dir():
                continue
            selected = {path.name for path in self._selected_profile_files(profile_dir)}
            clips = []
            for path in self._profile_wavs(profile_dir):
                details = self._wav_details(path)
                clips.append({
                    "name": path.name,
                    "label": path.stem,
                    "duration_seconds": details["duration_seconds"],
                    "supported": details["supported"],
                    "sample_rate": details["sample_rate"],
                    "selected": path.name in selected,
                    "url": f"/api/tts/reference-audio?reference={quote(path.relative_to(VOICE_DATA_DIR).as_posix())}",
                    "ref_text": self._clip_transcript(path),
                })
            if clips:
                profiles.append({"id": profile_dir.name, "clips": clips})
        return profiles

    def set_voice_selection(self, profile: str, files: list[str]) -> dict:
        profile_dir = self._profile_directory(profile)
        if profile_dir is None:
            raise ValueError("音色不存在")
        if not isinstance(files, list) or not files or len(files) > VOICE_UPLOAD_MAX_FILES:
            raise ValueError("至少选择一个参与合成的音频")
        wavs = {path.name: path for path in self._profile_wavs(profile_dir)}
        if any(not isinstance(name, str) or name not in wavs for name in files) or len(set(files)) != len(files):
            raise ValueError("所选音频无效或重复")
        selected_paths = [wavs[name] for name in files]
        self._combine_profile_audio(selected_paths)
        selection_path = profile_dir / "selection.json"
        if selection_path.is_symlink():
            raise ValueError("音色选择配置不能是符号链接")
        temporary = profile_dir / f".selection-{os.getpid()}-{threading.get_ident()}.tmp"
        temporary.write_text(json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(selection_path)
        return next((item for item in self.voice_profiles() if item["id"] == profile), {"id": profile, "clips": []})

    def _reference_path(self, reference: str) -> Path:
        if not isinstance(reference, str) or not reference or "\\" in reference:
            raise ValueError("Invalid reference audio name")
        parts = Path(reference).parts
        if len(parts) == 1:
            parts = ("atri", parts[0])
        if len(parts) != 2 or any(part in {"", ".", ".."} for part in parts) or Path(parts[1]).suffix.lower() != ".wav":
            raise ValueError("Invalid reference audio name")
        profile_dir = VOICE_DATA_DIR / parts[0]
        path = profile_dir / parts[1]
        try:
            path.resolve().relative_to(VOICE_DATA_DIR.resolve())
        except ValueError as exc:
            raise ValueError("Invalid reference audio name") from exc
        if profile_dir.is_symlink() or path.is_symlink() or not path.is_file():
            raise ValueError(f"Reference audio not found: {reference}")
        return path

    def reference_path(self, reference: str) -> Path:
        return self._reference_path(reference)

    def _reference_transcript(self, reference: str) -> str:
        profile_dir = self._profile_directory(reference)
        if profile_dir is not None:
            return self._profile_transcript(self._selected_profile_files(profile_dir))
        path = self._reference_path(reference)
        return self._clip_transcript(path) or ""

    def _combine_profile_audio(self, files: list[Path]) -> tuple[bytes, str]:
        if not files:
            raise ValueError("音色没有选中参与合成的音频")
        samples = array("h")
        sample_rate = None
        stamps = []
        for index, path in enumerate(files):
            with wave.open(str(path), "rb") as audio:
                if audio.getsampwidth() != 2 or audio.getnchannels() not in (1, 2):
                    raise ValueError(f"仅支持 16-bit 单声道或双声道 WAV: {path.name}")
                if sample_rate is None:
                    sample_rate = audio.getframerate()
                elif audio.getframerate() != sample_rate:
                    raise ValueError("同一音色中参与合成的 WAV 采样率必须一致")
                clip = array("h")
                clip.frombytes(audio.readframes(audio.getnframes()))
                if audio.getnchannels() == 2:
                    clip = array("h", ((clip[i] + clip[i + 1]) // 2 for i in range(0, len(clip), 2)))
                if index:
                    samples.extend([0] * int(sample_rate * 0.12))
                samples.extend(clip)
            stamps.append(f"{path.name}:{path.stat().st_mtime_ns}")
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            audio.writeframes(samples.tobytes())
        selection_path = files[0].parent / "selection.json"
        if selection_path.is_file() and not selection_path.is_symlink():
            stamps.append(f"selection:{selection_path.stat().st_mtime_ns}")
        return output.getvalue(), ":".join(stamps)

    def _reference_audio(self, reference: str) -> tuple[bytes, str]:
        profile_dir = self._profile_directory(reference)
        if profile_dir is not None:
            return self._combine_profile_audio(self._selected_profile_files(profile_dir))

        path = self._reference_path(reference)
        return path.read_bytes(), str(path.stat().st_mtime_ns)

    def _voice_name(self, reference: str, stamp: str, ref_text: str) -> str:
        key = f"{reference}\0{stamp}\0{ref_text}".encode("utf-8")
        return "voice-" + hashlib.sha256(key).hexdigest()[:16]

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
            ref_text = self._reference_transcript(reference)
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
