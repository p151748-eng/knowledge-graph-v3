"""
AgentPipeline: 3-Agent 流水线编排器。
顺序执行 KGRetriever → Explainer → Integrator。
"""

import asyncio
import logging
from functools import partial
from typing import Any, AsyncGenerator
from sqlalchemy.orm import Session

from core.agent import BaseAgent, AgentResult
from core.context import AgentContext, PipelineData
from models.schemas import RetrievalData, ExplanationData, IntegrationData
from agents.kg_retriever import KGRetrieverAgent
from agents.explainer import ExplainerAgent
from agents.integrator import IntegratorAgent
from llm.manager import llm_manager

logger = logging.getLogger(__name__)


class AgentPipeline:
    """3-Agent 流水线编排器"""

    def __init__(self, db: Session):
        self.db = db
        self.retriever = KGRetrieverAgent(db, llm_manager)
        self.explainer = ExplainerAgent(llm_manager)
        self.integrator = IntegratorAgent(llm_manager)

    def run(self, context: AgentContext) -> AgentResult:
        """
        顺序执行 KGRetriever → Explainer → Integrator。

        每步记录并返回中间状态。
        """
        results = {}

        # Step 1: KGRetriever
        logger.info("[Pipeline] 执行 KGRetriever...")
        r1 = self.retriever.run(context)
        results["retriever"] = r1
        if not r1.success:
            return AgentResult(success=False, output=results, message="KGRetriever 失败")
        logger.info(f"[Pipeline] KGRetriever 完成: {r1.message}")

        # Step 2: Explainer
        logger.info("[Pipeline] 执行 Explainer...")
        r2 = self.explainer.run(context)
        results["explainer"] = r2
        if not r2.success:
            logger.warning(f"[Pipeline] Explainer 失败（继续）: {r2.message}")
        else:
            logger.info(f"[Pipeline] Explainer 完成: {r2.message}")

        # Step 3: Integrator
        logger.info("[Pipeline] 执行 Integrator...")
        r3 = self.integrator.run(context)
        results["integrator"] = r3
        if not r3.success:
            return AgentResult(success=False, output=results, message="Integrator 失败")

        logger.info("[Pipeline] 流水线执行完成")
        return r3

    async def run_async(self, context: AgentContext) -> AsyncGenerator[dict, None]:
        """
        异步执行流水线，yield 每步状态（SSE 推送用）。
        所有同步调用都放到线程池，避免阻塞事件循环。
        """
        import time
        loop = asyncio.get_running_loop()

        # Step 1: KGRetriever
        start = time.time()
        yield {
            "type": "status",
            "agent": "KGRetriever",
            "step": "检索中",
            "elapsed": 0.0,
        }

        r1 = await loop.run_in_executor(None, self.retriever.run, context)
        elapsed = time.time() - start
        yield {
            "type": "status",
            "agent": "KGRetriever",
            "step": "检索完成",
            "elapsed": elapsed,
        }

        if not r1.success:
            yield {"type": "error", "message": r1.message}
            return

        # Step 2: Explainer
        start = time.time()
        yield {
            "type": "status",
            "agent": "Explainer",
            "step": "理解分析中",
            "elapsed": elapsed,
        }

        r2 = await loop.run_in_executor(None, self.explainer.run, context)
        elapsed += time.time() - start
        yield {
            "type": "status",
            "agent": "Explainer",
            "step": "理解完成",
            "elapsed": elapsed,
        }

        if r2.success and r2.output:
            yield {
                "type": "explanations",
                "data": r2.output.get("explanations", []),
            }

        # Step 3: Integrator
        start = time.time()
        yield {
            "type": "status",
            "agent": "Integrator",
            "step": "生成回答中",
            "elapsed": elapsed,
        }

        r3 = await loop.run_in_executor(None, self.integrator.run, context)
        elapsed += time.time() - start

        if r3.success and r3.output:
            answer = r3.output.get("answer", "")
            for char in answer:
                yield {"type": "delta", "content": char}

            yield {
                "type": "sources",
                "data": r3.output.get("sources", []),
            }

        yield {
            "type": "status",
            "agent": "Integrator",
            "step": "完成",
            "elapsed": elapsed,
        }

        yield {
            "type": "metrics",
            "path": "pipeline",
            "processing_time": f"{elapsed:.1f}s",
            "confidence": r3.output.get("confidence", 0.5) if r3.output else 0.5,
        }
