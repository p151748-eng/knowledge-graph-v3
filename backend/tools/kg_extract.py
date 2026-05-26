"""
KGExtractTool: LLM 实体抽取工具。
从文本中使用 LLM 抽取实体和关系。
"""

import json
from typing import Any, Dict, List
from sqlalchemy.orm import Session

from tools.base import BaseTool
from llm.manager import llm_manager


EXTRACTION_PROMPT = """你是一个知识图谱专家。请从以下文本中抽取实体和关系。

文本：
{text}

请以JSON格式返回，包含以下结构：
{{
  "entities": [
    {{"name": "实体名称", "type": "entity/concept/document", "description": "简短描述"}}
  ],
  "relations": [
    {{"source": "源实体", "target": "目标实体", "relation": "关系类型"}}
  ]
}}

要求：
- 只抽取有明确名称的实体，不要抽取泛泛的概念
- 关系应该简洁，如"依赖于"、"属于"、"用于"等
- 类型只使用 entity/concept/document 三种
- 返回纯JSON，不要包含任何其他文字
"""


class KGExtractTool(BaseTool):
    """实体抽取工具"""

    name = "kg_extract"
    description = "从文本中使用 LLM 抽取实体和关系"

    def __init__(self, db: Session, llm=None):
        self.db = db
        self.llm = llm if llm is not None else llm_manager

    def execute(self, text: str, **kwargs) -> Dict[str, Any]:
        """
        从文本中抽取实体和关系。

        返回:
        {
            "entities": [...],
            "relations": [...],
        }
        """
        try:
            prompt = EXTRACTION_PROMPT.format(text=text)
            result = self.llm.complete_json(prompt, {})
            return result
        except Exception as e:
            # 抽取失败时返回空结果
            return {"entities": [], "relations": []}
