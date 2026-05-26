"""
LLMClient: 统一的多提供商 LLM 客户端。
默认使用 DashScope (Qwen)，也支持 OpenAI / Anthropic / DeepSeek。
"""

import json
import http.client
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from config import config


class LLMResponse:
    """LLM 返回封装"""
    def __init__(self, content: str, model: str, provider: str):
        self.content = content
        self.model = model
        self.provider = provider


class LLMClient:
    """统一 LLM 客户端"""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider or config.LLM_PROVIDER
        self.model = model or config.LLM_MODEL
        self.temperature = config.LLM_TEMPERATURE
        self._embedding_model = config.EMBEDDING_MODEL

    def complete(self, prompt: str, system_prompt: str = "", history: Optional[List[Dict[str, str]]] = None, **kwargs) -> LLMResponse:
        """
        统一的对话生成接口。
        按 self.provider 分发到具体实现。
        history: 对话历史 [{"role": "user/assistant", "content": "..."}]，插入在 system 之后、当前 prompt 之前。
        """
        if self.provider == "dashscope":
            return self._call_dashscope(prompt, system_prompt, history, **kwargs)
        elif self.provider == "openai":
            return self._call_openai(prompt, system_prompt, history, **kwargs)
        elif self.provider == "anthropic":
            return self._call_anthropic(prompt, system_prompt, history, **kwargs)
        elif self.provider == "deepseek":
            return self._call_deepseek(prompt, system_prompt, history, **kwargs)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def complete_json(self, prompt: str, json_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        结构化 JSON 输出（用于实体抽取等场景）。
        目前通过 DashScope 的 JSON mode 或解析文本实现。
        """
        response = self.complete(
            prompt + "\n\n请以合法的 JSON 格式返回上述内容，不要包含其他文字。",
            ""
        )
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取 JSON
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            return json.loads(content)

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        向量嵌入。
        支持独立配置 embedding provider，默认保持原有 DashScope/OpenAI 逻辑。
        """
        provider = (config.EMBEDDING_PROVIDER or "auto").lower()
        if provider in {"openai", "openai_compatible", "xfyun"}:
            return self._embed_openai_compatible(texts, config.EMBEDDING_API_KEY, config.EMBEDDING_BASE_URL)
        if provider == "dashscope":
            return self._embed_dashscope(texts)
        if config.QWEN_API_KEY:
            return self._embed_dashscope(texts)
        return self._embed_openai(texts)

    # ── DashScope (Qwen) ──────────────────────────────────────────

    def _call_dashscope(self, prompt: str, system: str = "", history: Optional[List[Dict[str, str]]] = None, **kwargs) -> LLMResponse:
        """调用阿里 DashScope OpenAI 兼容 API (Qwen)"""
        api_key = config.QWEN_API_KEY
        if not api_key:
            raise ValueError("QWEN_API_KEY not configured")

        parsed = urlparse(config.QWEN_BASE_URL)
        conn = http.client.HTTPSConnection(parsed.netloc)
        base_path = parsed.path.rstrip("/")
        request_path = f"{base_path}/chat/completions" if base_path else "/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": config.QWEN_MODEL or self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
        })

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            conn.request("POST", request_path, payload, headers)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode())

            if resp.status != 200:
                raise Exception(f"DashScope API error: {data}")

            content = data["choices"][0]["message"]["content"]
            return LLMResponse(content=content, model=config.QWEN_MODEL or self.model, provider="dashscope")
        finally:
            conn.close()

    def _embed_dashscope(self, texts: List[str]) -> List[List[float]]:
        """调用 DashScope embedding API"""
        api_key = config.QWEN_API_KEY
        if not api_key:
            raise ValueError("QWEN_API_KEY not configured")

        conn = http.client.HTTPSConnection("dashscope.aliyuncs.com")
        payload = json.dumps({
            "model": "text-embedding-v3",
            "input": {"texts": texts}
        })
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            conn.request("POST", "/api/v1/services/embeddings/embedding", payload, headers)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode())

            if resp.status != 200:
                raise Exception(f"DashScope embedding error: {data}")

            embeddings = data["output"]["embeddings"]
            return [e["embedding"] for e in embeddings]
        finally:
            conn.close()

    # ── OpenAI ──────────────────────────────────────────────────

    def _call_openai(self, prompt: str, system: str = "", history: Optional[List[Dict[str, str]]] = None, **kwargs) -> LLMResponse:
        """调用 OpenAI / OpenAI-compatible API"""
        api_key = config.OPENAI_API_KEY
        base_url = config.OPENAI_BASE_URL

        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"Invalid OpenAI base URL: {base_url}")
        conn = http.client.HTTPSConnection(parsed.netloc)
        base_path = parsed.path.rstrip("/")
        request_path = f"{base_path}/chat/completions" if base_path else "/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "reasoning_effort": kwargs.get("reasoning_effort", "low"),
        })

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            conn.request("POST", request_path, payload, headers)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode())
            if resp.status >= 400:
                raise Exception(f"OpenAI-compatible API error: {data}")

            content = data["choices"][0]["message"]["content"]
            return LLMResponse(content=content, model=self.model, provider="openai")
        finally:
            conn.close()

    def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        """调用 OpenAI embedding API"""
        return self._embed_openai_compatible(texts, config.OPENAI_API_KEY, config.OPENAI_BASE_URL)

    def _embed_openai_compatible(self, texts: List[str], api_key: Optional[str], base_url: str) -> List[List[float]]:
        """调用 OpenAI 兼容 embedding API"""
        if not api_key:
            raise ValueError("Embedding API key not configured")

        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"Invalid embedding base URL: {base_url}")

        path = parsed.path.rstrip("/")
        request_path = path if path.endswith("/embeddings") else f"{path}/embeddings"
        conn = http.client.HTTPSConnection(parsed.netloc)
        payload = json.dumps({
            "model": self._embedding_model,
            "input": texts,
        })

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            conn.request("POST", request_path, payload, headers)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode())
            if resp.status >= 400:
                raise Exception(f"OpenAI-compatible embedding error: {data}")
            return [e["embedding"] for e in data["data"]]
        finally:
            conn.close()

    # ── Anthropic ────────────────────────────────────────────────

    def _call_anthropic(self, prompt: str, system: str = "", history: Optional[List[Dict[str, str]]] = None, **kwargs) -> LLMResponse:
        """调用 Anthropic 兼容 Messages API"""
        api_key = config.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN not configured")

        parsed = urlparse(config.ANTHROPIC_BASE_URL)
        conn = http.client.HTTPSConnection(parsed.netloc)
        base_path = parsed.path.rstrip("/")
        request_path = f"{base_path}/v1/messages" if base_path else "/v1/messages"
        messages = []
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        payload = json.dumps({
            "model": config.ANTHROPIC_MODEL or self.model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": kwargs.get("temperature", self.temperature),
            "system": system if system else None,
        })

        headers = {
            "x-api-key": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

        try:
            conn.request("POST", request_path, payload, headers)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode())
            if resp.status >= 400:
                raise Exception(f"Anthropic API error: {data}")
            content = data["content"][0]["text"]
            return LLMResponse(content=content, model=config.ANTHROPIC_MODEL or self.model, provider="anthropic")
        finally:
            conn.close()

    # ── DeepSeek ────────────────────────────────────────────────

    def _call_deepseek(self, prompt: str, system: str = "", history: Optional[List[Dict[str, str]]] = None, **kwargs) -> LLMResponse:
        """调用 DeepSeek API"""
        api_key = config.DEEPSEEK_API_KEY
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not configured")

        parsed = urlparse(config.DEEPSEEK_BASE_URL)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"Invalid DeepSeek base URL: {config.DEEPSEEK_BASE_URL}")
        base_path = parsed.path.rstrip("/")
        request_path = f"{base_path}/chat/completions" if base_path else "/chat/completions"
        conn = http.client.HTTPSConnection(parsed.netloc)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
        })

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            conn.request("POST", request_path, payload, headers)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode())
            if resp.status >= 400:
                raise Exception(f"DeepSeek API error: {data}")
            content = data["choices"][0]["message"]["content"]
            return LLMResponse(content=content, model=self.model, provider="deepseek")
        finally:
            conn.close()


# 全局单例
llm_client = LLMClient()
