from .base_llm import BaseLLM
from .openai_llm import OpenAILLM

try:
    from .modelscope_llm import ModelScopeLLM
except ImportError:
    # 本地依赖（如 torch、transformers、modelscope）未安装时不影响 OpenAI 模块使用
    ModelScopeLLM = None  # type: ignore[misc, assignment]

__all__ = ['BaseLLM', 'ModelScopeLLM', 'OpenAILLM']
