"""
LangSmith 连通性测试。

运行方式：
    python backend/tests/test_langsmith_connectivity.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import config
from observability.langsmith_tracing import is_enabled, mask_secret


def main():
    assert config.LANGSMITH_TRACING is True, "LANGSMITH_TRACING 未开启"
    assert config.LANGSMITH_API_KEY, "LANGSMITH_API_KEY 未配置"
    assert is_enabled() is True, "LangSmith tracing helper 未启用"

    try:
        from langsmith import Client
    except Exception as exc:
        raise AssertionError("未安装 langsmith，请先运行 pip install -r backend/requirements.txt") from exc

    client = Client(api_key=config.LANGSMITH_API_KEY, api_url=config.LANGSMITH_ENDPOINT)
    project_name = config.LANGSMITH_PROJECT
    project = client.create_project(project_name=project_name, description="KG paper assistant tracing", upsert=True)

    print("=== LangSmith 连通测试通过 ===")
    print(f"project={project_name}")
    print(f"endpoint={config.LANGSMITH_ENDPOINT}")
    print(f"api_key={mask_secret(config.LANGSMITH_API_KEY)}")
    print(f"project_id={getattr(project, 'id', None)}")


if __name__ == "__main__":
    main()
