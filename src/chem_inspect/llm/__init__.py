"""模型客户端（Adapters）。"""

from .base import LLMClient, LLMResult
from .maas import MaasClient, MaasError, to_data_url

__all__ = ["LLMClient", "LLMResult", "MaasClient", "MaasError", "to_data_url"]
