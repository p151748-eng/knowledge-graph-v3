"""
LLM Manager: 动态 LLM 客户端管理器。
支持运行时切换 LLM 提供商和模型，无需重启服务。
"""

import os
import threading
from typing import Optional
from config import config
from observability.langsmith_tracing import traceable


class LLMManager:
    """
    LLM 客户端管理器。
    支持动态切换提供商和模型。
    """

    _instance: Optional["LLMManager"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._provider = config.LLM_PROVIDER
            self._model = config.LLM_MODEL
            self._temperature = config.LLM_TEMPERATURE
            self._client = None
            self._update_client()

    def _update_client(self):
        """更新 LLM 客户端"""
        from llm.client import LLMClient
        self._client = LLMClient(
            provider=self._provider,
            model=self._model,
        )
        self._client.temperature = self._temperature

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def temperature(self) -> float:
        return self._temperature

    def set_provider(self, provider: str) -> bool:
        """设置 LLM 提供商"""
        valid_providers = ["dashscope", "openai", "anthropic", "deepseek"]
        if provider not in valid_providers:
            raise ValueError(f"不支持的提供商: {provider}，可选: {valid_providers}")

        # 检查 API key
        if provider == "dashscope" and not config.QWEN_API_KEY:
            raise ValueError("未配置 QWEN_API_KEY")
        elif provider == "openai" and not config.OPENAI_API_KEY:
            raise ValueError("未配置 OPENAI_API_KEY")
        elif provider == "anthropic" and not config.ANTHROPIC_API_KEY:
            raise ValueError("未配置 ANTHROPIC_API_KEY")
        elif provider == "deepseek" and not config.DEEPSEEK_API_KEY:
            raise ValueError("未配置 DEEPSEEK_API_KEY")

        with self._lock:
            self._provider = provider
            self._update_client()

        return True

    def set_model(self, model: str) -> bool:
        """设置模型"""
        with self._lock:
            self._model = model
            self._update_client()
        return True

    def set_temperature(self, temperature: float) -> bool:
        """设置温度"""
        if not 0 <= temperature <= 2:
            raise ValueError("温度必须在 0-2 之间")
        with self._lock:
            self._temperature = temperature
            self._client.temperature = temperature
        return True

    def update_settings(self, provider: str = None, model: str = None, temperature: float = None) -> dict:
        """批量更新设置"""
        result = {}

        if provider is not None:
            self.set_provider(provider)
            result["provider"] = self._provider

        if model is not None:
            self.set_model(model)
            result["model"] = self._model

        if temperature is not None:
            self.set_temperature(temperature)
            result["temperature"] = self._temperature

        return result

    @property
    def client(self):
        """获取 LLM 客户端"""
        return self._client

    @traceable(name="llm.complete", run_type="llm")
    def complete(self, prompt: str, system_prompt: str = "", **kwargs):
        """对话生成"""
        return self._client.complete(prompt, system_prompt, **kwargs)

    @traceable(name="llm.complete_json", run_type="llm")
    def complete_json(self, prompt: str, json_schema: dict):
        """JSON 输出"""
        return self._client.complete_json(prompt, json_schema)

    @traceable(name="llm.embed", run_type="embedding")
    def embed(self, texts: list):
        """向量嵌入"""
        return self._client.embed(texts)


# 全局单例
llm_manager = LLMManager()
