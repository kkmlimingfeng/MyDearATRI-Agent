"""GGUF LLM adapter backed by llama.cpp.

The optional ``llama-cpp-python`` dependency is imported lazily so the rest of
the application can still start when a GGUF runtime is not installed.
"""
import os
import re
import inspect
import ctypes
import json
import site
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from agent.protocol import LLMResponse, ToolCall

from .base_llm import BaseLLM, StreamPreview


class GGUFLLM(BaseLLM):
    """Load a local GGUF model through ``llama-cpp-python``."""

    def __init__(
        self,
        module_id: str,
        bus,
        model_path: str,
        n_ctx: int = 8192,
        n_batch: int = 512,
        n_threads: Optional[int] = None,
        n_gpu_layers: int = 0,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        chat_format: Optional[str] = None,
        mmproj_path: Optional[str] = None,
        reasoning_format: Optional[str] = "qwen3",
        verbose: bool = False,
    ):
        super().__init__(module_id, bus)
        self.model_path = os.path.abspath(os.path.expanduser(model_path))
        self.n_ctx = n_ctx
        self.n_batch = n_batch
        self.n_threads = n_threads
        self.n_gpu_layers = n_gpu_layers
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.chat_format = chat_format
        self.mmproj_path = os.path.abspath(os.path.expanduser(mmproj_path)) if mmproj_path else ""
        self.reasoning_format = reasoning_format
        self.verbose = verbose
        self.model: Any = None
        self._cuda_library_handles = []

    def initialize(self) -> None:
        self._configure_cuda_runtime()
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ImportError(
                "使用 GGUFLLM 需要安装 llama-cpp-python；"
                "CPU 可执行 pip install llama-cpp-python，GPU 请按平台安装对应构建"
            ) from exc

        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(f"GGUF 模型文件不存在: {self.model_path}")
        if self.mmproj_path and not os.path.isfile(self.mmproj_path):
            raise FileNotFoundError(f"mmproj 文件不存在: {self.mmproj_path}")

        kwargs: Dict[str, Any] = {
            "model_path": self.model_path,
            "n_ctx": self.n_ctx,
            "n_batch": self.n_batch,
            "n_gpu_layers": self.n_gpu_layers,
            "verbose": self.verbose,
        }
        if self.n_threads is not None:
            kwargs["n_threads"] = self.n_threads
        if self.chat_format:
            kwargs["chat_format"] = self.chat_format
        if self.mmproj_path:
            try:
                from llama_cpp import llama_chat_format
            except ImportError as exc:
                raise RuntimeError(
                    "当前 llama-cpp-python 不包含多模态 chat handler，无法加载 mmproj；"
                    "请安装支持 multimodal 的构建"
                ) from exc
            handler_names = (
                "Qwen35ChatHandler",
                "Qwen3VLChatHandler",
                "Qwen25VLChatHandler",
                "Qwen2VLChatHandler",
                "Llava15ChatHandler",
            )
            handler_class = next(
                (getattr(llama_chat_format, name, None) for name in handler_names),
                None,
            )
            if handler_class is None:
                raise RuntimeError(
                    "当前 llama-cpp-python 没有可用的 Qwen/视觉 chat handler，无法加载 mmproj"
                )
            handler_parameters = inspect.signature(handler_class).parameters
            projection_argument = (
                "mmproj_path" if "mmproj_path" in handler_parameters else "clip_model_path"
            )
            kwargs["chat_handler"] = handler_class(**{projection_argument: self.mmproj_path})

        print(f"[gguf] 正在加载模型: {self.model_path}")
        self.model = Llama(**kwargs)
        self._initialized = True
        print("[gguf] 模型加载完成")

    def _configure_cuda_runtime(self) -> None:
        """Expose pip-installed CUDA runtime libraries to the native backend."""
        if self.n_gpu_layers == 0:
            return

        library_dirs = []
        for site_dir in site.getsitepackages():
            nvidia_dir = Path(site_dir) / "nvidia"
            if nvidia_dir.is_dir():
                library_dirs.extend(
                    str(path) for path in nvidia_dir.glob("*/lib") if path.is_dir()
                )

        # WSL supplies the driver library here; CUDA runtime packages supply the
        # remaining user-space libraries above.
        if sys.platform.startswith("linux"):
            library_dirs.extend(
                path for path in ("/usr/lib/wsl/lib", "/usr/local/cuda/lib64")
                if os.path.isdir(path)
            )

        if not library_dirs:
            return

        current = os.environ.get("LD_LIBRARY_PATH", "")
        existing = [path for path in current.split(os.pathsep) if path]
        merged = list(dict.fromkeys(library_dirs + existing))
        os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(merged)

        # Linux's dynamic loader reads LD_LIBRARY_PATH at process startup, so
        # loading llama.cpp later in this process needs the wheel dependencies
        # preloaded by absolute path first.
        if sys.platform.startswith("linux"):
            for library_name in (
                "libcudart.so.12",
                "libcublasLt.so.12",
                "libcublas.so.12",
                "libnccl.so.2",
            ):
                for library_dir in library_dirs:
                    library_path = Path(library_dir) / library_name
                    if library_path.exists():
                        try:
                            handle = ctypes.CDLL(
                                str(library_path), mode=ctypes.RTLD_GLOBAL
                            )
                        except OSError as exc:
                            raise RuntimeError(
                                f"无法加载 CUDA 运行库 {library_path}: {exc}"
                            ) from exc
                        self._cuda_library_handles.append(handle)
                        break

    def generate(self, messages: List[Dict[str, str]]) -> str:
        return self.generate_response(messages).content

    def generate_response(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        if self.model is None:
            raise RuntimeError("GGUF 模型尚未初始化")

        kwargs: Dict[str, Any] = {
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        if self.reasoning_format and self._supports_reasoning_format():
            kwargs["reasoning_format"] = self.reasoning_format
        response = self.model.create_chat_completion(**kwargs)
        return self._parse_completion(response)

    @staticmethod
    def _parse_completion(response: Dict[str, Any]) -> LLMResponse:
        choices = response.get("choices", [])
        if not choices:
            return LLMResponse(raw=response)
        message = choices[0].get("message", {})
        content = str(message.get("content") or "").strip()
        content = re.sub(r"^<think>.*?</think>\s*", "", content, count=1, flags=re.DOTALL)
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            calls.append(ToolCall(
                call_id=call.get("id", ""),
                name=function.get("name", ""),
                arguments=arguments if isinstance(arguments, dict) else {},
            ))
        return LLMResponse(
            content=content,
            tool_calls=calls,
            usage=response.get("usage") or {},
            raw=response,
        )

    def generate_response_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        on_progress: Callable[[str], None],
    ) -> LLMResponse:
        if self.model is None:
            raise RuntimeError("GGUF 模型尚未初始化")
        kwargs: Dict[str, Any] = {
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if self.reasoning_format and self._supports_reasoning_format():
            kwargs["reasoning_format"] = self.reasoning_format

        preview = StreamPreview(
            on_progress,
            wait_for_reasoning_end=self.reasoning_format == "qwen3" and "qwen3" in Path(self.model_path).name.lower(),
        )
        tool_parts = {}
        usage = {}
        generated_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        original_generate = self.model.generate
        had_generate_override = "generate" in vars(self.model)

        def capture_generate(prompt_tokens, *args, **generation_kwargs):
            generated_usage["prompt_tokens"] += len(prompt_tokens)
            for token in original_generate(prompt_tokens, *args, **generation_kwargs):
                generated_usage["completion_tokens"] += 1
                yield token

        # This llama-cpp-python build does not include usage in streamed chunks.
        # Its generate() iterator exposes the actual prompt and sampled tokens.
        self.model.generate = capture_generate
        try:
            try:
                chunks = self.model.create_chat_completion(**kwargs)
            except TypeError as exc:
                if "stream" not in str(exc).lower():
                    raise
                return self.generate_response(messages, tools=tools)
            if isinstance(chunks, dict):
                return self._parse_completion(chunks)
            for chunk in chunks:
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        preview.push(str(delta["content"]))
                    for tool in delta.get("tool_calls") or []:
                        part = tool_parts.setdefault(tool.get("index", 0), {"id": "", "name": "", "arguments": ""})
                        if tool.get("id"):
                            part["id"] = tool["id"]
                        function = tool.get("function") or {}
                        part["name"] += function.get("name") or ""
                        part["arguments"] += function.get("arguments") or ""
        finally:
            if had_generate_override:
                self.model.generate = original_generate
            else:
                del self.model.generate
        calls = []
        for part in tool_parts.values():
            try:
                arguments = json.loads(part["arguments"] or "{}")
            except (TypeError, json.JSONDecodeError):
                arguments = {}
            calls.append(ToolCall(call_id=part["id"], name=part["name"], arguments=arguments))
        if generated_usage["prompt_tokens"]:
            generated_usage["total_tokens"] = sum(generated_usage.values())
        return LLMResponse(content=preview.content, tool_calls=calls, usage=usage or generated_usage)

    def _supports_reasoning_format(self) -> bool:
        """Return whether the installed llama-cpp binding exposes this option."""
        try:
            return "reasoning_format" in inspect.signature(
                self.model.create_chat_completion
            ).parameters
        except (TypeError, ValueError):
            # Older Cython builds may not expose a signature.  Let the call
            # proceed without the optional argument for maximum compatibility.
            return False

    def shutdown(self) -> None:
        self.model = None
        self._initialized = False
        print("[gguf] 模型已卸载")
