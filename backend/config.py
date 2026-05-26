"""
Config: 应用配置管理
支持从环境变量和动态配置加载。
"""

import os
import threading
import json
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
BASE_DIR = BACKEND_DIR.parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)

# 配置文件路径（用于动态配置）
CONFIG_FILE = BASE_DIR / "config.json"


class Config:
    """集中化配置管理"""

    _lock = threading.Lock()
    _settings_cache: dict = {}

    def __init__(self):
        self._load_dynamic_settings()

    def _load_dynamic_settings(self):
        """从文件加载动态配置（覆盖环境变量）"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._settings_cache = json.load(f)
            except Exception:
                self._settings_cache = {}

    def _save_dynamic_settings(self):
        """保存动态配置到文件"""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings_cache, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _get(self, key: str, default=None):
        """获取配置（动态配置优先于环境变量）"""
        if key in self._settings_cache:
            return self._settings_cache[key]
        return os.getenv(key, default)

    def _set(self, key: str, value):
        """设置配置"""
        with self._lock:
            self._settings_cache[key] = value
            self._save_dynamic_settings()

    # ── LLM 提供商 ──────────────────────────────────────────────
    @property
    def LLM_PROVIDER(self) -> str:
        return self._get("LLM_PROVIDER", "dashscope")

    @LLM_PROVIDER.setter
    def LLM_PROVIDER(self, value: str):
        self._set("LLM_PROVIDER", value)

    @property
    def LLM_MODEL(self) -> str:
        return self._get("LLM_MODEL", "qwen-plus")

    @LLM_MODEL.setter
    def LLM_MODEL(self, value: str):
        self._set("LLM_MODEL", value)

    @property
    def LLM_TEMPERATURE(self) -> float:
        val = self._get("LLM_TEMPERATURE", "0.7")
        return float(val)

    @LLM_TEMPERATURE.setter
    def LLM_TEMPERATURE(self, value: float):
        self._set("LLM_TEMPERATURE", float(value))

    # ── API Keys ────────────────────────────────────────────────
    @property
    def OPENAI_API_KEY(self) -> Optional[str]:
        return os.getenv("OPENAI_API_KEY")

    @property
    def OPENAI_BASE_URL(self) -> str:
        return os.getenv(
            "OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

    @property
    def OPENAI_EMBEDDING_MODEL(self) -> str:
        return os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-v3")

    @property
    def EMBEDDING_PROVIDER(self) -> str:
        return self._get("EMBEDDING_PROVIDER", "auto")

    @property
    def EMBEDDING_API_KEY(self) -> Optional[str]:
        return self._get("EMBEDDING_API_KEY") or self.OPENAI_API_KEY

    @property
    def EMBEDDING_BASE_URL(self) -> str:
        return self._get("EMBEDDING_BASE_URL", self.OPENAI_BASE_URL)

    @property
    def EMBEDDING_MODEL(self) -> str:
        return self._get("EMBEDDING_MODEL", self.OPENAI_EMBEDDING_MODEL)

    @property
    def ANTHROPIC_API_KEY(self) -> Optional[str]:
        return os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")

    @property
    def ANTHROPIC_BASE_URL(self) -> str:
        return os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    @property
    def ANTHROPIC_MODEL(self) -> str:
        return os.getenv("ANTHROPIC_MODEL", self.LLM_MODEL)

    @property
    def DEEPSEEK_API_KEY(self) -> Optional[str]:
        return os.getenv("DEEPSEEK_API_KEY")

    @property
    def DEEPSEEK_BASE_URL(self) -> str:
        return os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

    @property
    def QWEN_API_KEY(self) -> Optional[str]:
        return os.getenv("QWEN_API_KEY")

    @property
    def QWEN_BASE_URL(self) -> str:
        return os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    @property
    def QWEN_MODEL(self) -> str:
        return os.getenv("QWEN_MODEL", self.LLM_MODEL)

    # ── 数据库 ─────────────────────────────────────────────────
    @property
    def DATABASE_URL(self) -> str:
        return os.getenv(
            "DATABASE_URL",
            "mysql+pymysql://root:your-password@localhost:3306/konw"
        )

    # ── 服务 ──────────────────────────────────────────────────
    @property
    def HOST(self) -> str:
        return os.getenv("HOST", "0.0.0.0")

    @property
    def PORT(self) -> int:
        return int(os.getenv("PORT", "8003"))

    @property
    def DEBUG(self) -> bool:
        return os.getenv("DEBUG", "true").lower() in ("true", "1", "yes")

    @property
    def SQL_ECHO(self) -> bool:
        return os.getenv("SQL_ECHO", "false").lower() in ("true", "1", "yes")

    # ── 联网搜索 ────────────────────────────────────────────────
    @property
    def WEB_SEARCH_MAX_RESULTS(self) -> int:
        return int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))

    @property
    def WEB_SEARCH_AUTO_SAVE(self) -> bool:
        return os.getenv("WEB_SEARCH_AUTO_SAVE", "true").lower() in ("true", "1", "yes")

    # ── Chroma ─────────────────────────────────────────────────
    @property
    def CHROMA_PERSIST_DIR(self) -> str:
        return os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "chroma_data"))

    # ── CRAG / Self-RAG ─────────────────────────────────────────────
    @property
    def CRAG_MAX_LOCAL_ROUNDS(self) -> int:
        return int(os.getenv("CRAG_MAX_LOCAL_ROUNDS", "2"))

    @property
    def CRAG_ALLOW_WEB(self) -> bool:
        return os.getenv("CRAG_ALLOW_WEB", "true").lower() in ("true", "1", "yes")

    @property
    def CRAG_WEB_MAX_RESULTS(self) -> int:
        return int(os.getenv("CRAG_WEB_MAX_RESULTS", "5"))

    @property
    def CRAG_WEB_SAVE_ENABLED(self) -> bool:
        return os.getenv("CRAG_WEB_SAVE_ENABLED", "false").lower() in ("true", "1", "yes")

    @property
    def CRAG_MIN_RELEVANCE(self) -> float:
        return float(os.getenv("CRAG_MIN_RELEVANCE", "0.70"))

    @property
    def CRAG_MIN_SUPPORT(self) -> float:
        return float(os.getenv("CRAG_MIN_SUPPORT", "0.70"))

    @property
    def CRAG_MIN_COVERAGE(self) -> float:
        return float(os.getenv("CRAG_MIN_COVERAGE", "0.65"))

    @property
    def CRAG_WEB_MIN_SCORE(self) -> float:
        return float(os.getenv("CRAG_WEB_MIN_SCORE", "0.75"))

    # ── JWT ────────────────────────────────────────────────────
    @property
    def JWT_SECRET_KEY(self) -> str:
        return os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")

    @property
    def JWT_ALGORITHM(self) -> str:
        return os.getenv("JWT_ALGORITHM", "HS256")

    @property
    def JWT_ACCESS_TOKEN_EXPIRE_MINUTES(self) -> int:
        return int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    # ── LangSmith ───────────────────────────────────────────────
    @property
    def LANGSMITH_TRACING(self) -> bool:
        return os.getenv("LANGSMITH_TRACING", "false").lower() in ("true", "1", "yes")

    @property
    def LANGSMITH_API_KEY(self) -> Optional[str]:
        return os.getenv("LANGSMITH_API_KEY")

    @property
    def LANGSMITH_PROJECT(self) -> str:
        return os.getenv("LANGSMITH_PROJECT", "kg-paper-assistant")

    @property
    def LANGSMITH_ENDPOINT(self) -> str:
        return os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")


config = Config()
