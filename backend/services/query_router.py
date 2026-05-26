"""
QueryRouter: 查询路由器。
规则路由负责稳定兜底，复杂问题再调用 LLM 进行意图识别和 query 优化。
"""

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RetrievalPlan:
    """检索执行计划"""
    bm25: bool = True
    vector: bool = True
    graph: bool = False
    community: bool = False
    bm25_top_k: int = 8
    vector_top_k: int = 8
    graph_top_k: int = 8
    graph_depth: int = 1
    query_type: str = "default"
    intent: str = "default"
    optimized_query: str = ""
    expanded_queries: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    graph_method: str = "none"
    confidence: float = 0.6
    reason: str = "规则路由"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# 闲聊 / 无需检索
CASUAL_PATTERNS = [
    "你好", "hello", "hi", "嗨", "谢谢", "你是谁",
    "早上好", "晚安", "再见", "ok", "好的",
]

# 全局总结 / 综述
GLOBAL_PATTERNS = [
    "整体", "总体", "总结", "概览", "框架", "架构",
    "主要有哪些", "梳理一下", "综述", "全局", "都有哪些",
    "包含哪些", "分类", "体系", "全景",
]

# 关系 / 多跳
RELATION_PATTERNS = [
    "关系", "关联", "影响", "依赖", "联系", "路径",
    "为什么", "如何导致", "怎么配合", "链路", "原因",
    "之间", "互相", "因果", "传导",
]

# 局部结构 / 上下游
STRUCTURE_PATTERNS = [
    "围绕", "上下游", "局部", "模块", "组织", "组成",
]

# 精确实体 / 术语 / 代码标识
EXACT_REGEX_PATTERNS = [
    r"[A-Za-z_][A-Za-z0-9_]{2,}",
    r"[A-Z]{2,}",
]

# 语义解释型
SEMANTIC_PATTERNS = [
    "怎么", "如何", "优化", "改进", "设计",
    "方案", "建议", "区别", "优缺点", "对比",
    "原理", "机制", "什么是", "解释",
]

AMBIGUOUS_PATTERNS = ["这个", "那个", "它", "它们", "这块", "上面", "刚才", "前面"]
GRAPH_METHODS = {"none", "ego", "path", "subgraph"}
INTENTS = {
    "fact", "explain", "compare", "relation", "path", "subgraph",
    "global_summary", "troubleshoot", "optimize", "chat", "default", "semantic", "exact",
}

LLM_ROUTER_PROMPT = """你是检索路由器。你的任务不是回答问题，而是判断应该如何检索。

请根据用户原始问题、最近对话上下文、相似提问模板和规则路由初判，输出纯 JSON。

用户原始问题：
{query}

最近对话上下文：
{context}

相似提问模板：
{templates}

规则路由初判：
{rule_plan}

输出 JSON 字段：
- intent: fact | explain | compare | relation | path | subgraph | global_summary | troubleshoot | optimize | chat
- optimized_query: 改写后的检索问题
- expanded_queries: 最多 3 个补充检索问题
- entities: 问题中明确出现或上下文明确指代的核心实体
- retrieval: {{"bm25": true, "vector": true, "graph": true, "community": false, "web": false}}
- graph_method: none | ego | path | subgraph
- top_k: {{"bm25": 8, "vector": 8, "graph": 10}}
- confidence: 0.0 到 1.0
- reason: 简短说明为什么这样路由

要求：
- 不要回答用户问题。
- 不要编造实体。
- 如果问题简单，尽量少检索。
- 如果需要图检索，只能选择 ego/path/subgraph/none。
- 如果不确定，保守选择 BM25 + Vector。
- 只返回 JSON，不要包含 Markdown。
"""


def route_query(
    query: str,
    context: Optional[str] = None,
    use_llm: bool = True,
    llm: Any = None,
    templates: Optional[List[Dict[str, Any]]] = None,
) -> RetrievalPlan:
    """分析查询，返回检索执行计划。"""
    rule_plan = route_by_rules(query)
    rule_plan.optimized_query = query.strip()

    if not use_llm or not should_use_llm(query, rule_plan):
        return rule_plan

    try:
        if templates is None:
            templates = _retrieve_query_templates(query, llm)
        llm_result = route_by_llm(query, rule_plan, context or "", templates, llm)
        return merge_rule_and_llm_plan(rule_plan, llm_result)
    except Exception:
        return rule_plan


def route_by_rules(query: str) -> RetrievalPlan:
    """规则路由，作为 LLM Router 的兜底。"""
    q = query.strip()
    q_lower = q.lower()

    if len(q) <= 2:
        return RetrievalPlan(
            bm25=False,
            vector=False,
            graph=False,
            query_type="casual",
            intent="chat",
            confidence=0.95,
            reason="极短查询，按闲聊处理",
        )

    if any(p in q_lower for p in CASUAL_PATTERNS) and len(q) <= 15:
        return RetrievalPlan(
            bm25=False,
            vector=False,
            graph=False,
            query_type="casual",
            intent="chat",
            confidence=0.95,
            reason="命中闲聊模式",
        )

    if any(p in q for p in GLOBAL_PATTERNS):
        is_local_structure = any(p in q for p in ["围绕", "上下游", "局部"])
        return RetrievalPlan(
            bm25=True,
            vector=True,
            graph=is_local_structure,
            community=not is_local_structure,
            bm25_top_k=8,
            vector_top_k=10,
            graph_top_k=10 if is_local_structure else 0,
            graph_depth=2 if is_local_structure else 1,
            query_type="subgraph" if is_local_structure else "global_summary",
            intent="subgraph" if is_local_structure else "global_summary",
            graph_method="subgraph" if is_local_structure else "none",
            confidence=0.75,
            reason="命中局部结构/全局总结模式",
        )

    if any(p in q for p in STRUCTURE_PATTERNS):
        return RetrievalPlan(
            bm25=True,
            vector=True,
            graph=True,
            bm25_top_k=8,
            vector_top_k=10,
            graph_top_k=10,
            graph_depth=2,
            query_type="subgraph",
            intent="subgraph",
            graph_method="subgraph",
            confidence=0.78,
            reason="命中局部结构/上下游模式",
        )

    if any(p in q for p in RELATION_PATTERNS):
        graph_method = "subgraph" if any(p in q for p in ["围绕", "上下游", "局部", "结构", "模块"]) else "path"
        intent = "subgraph" if graph_method == "subgraph" else "relation"
        return RetrievalPlan(
            bm25=True,
            vector=True,
            graph=True,
            bm25_top_k=8,
            vector_top_k=8,
            graph_top_k=10,
            graph_depth=2,
            query_type=intent,
            intent=intent,
            graph_method=graph_method,
            confidence=0.75,
            reason="命中关系/结构图检索模式",
        )

    if any(re.search(p, q) for p in EXACT_REGEX_PATTERNS):
        return RetrievalPlan(
            bm25=True,
            vector=True,
            graph=True,
            bm25_top_k=10,
            vector_top_k=5,
            graph_top_k=6,
            graph_depth=1,
            query_type="exact",
            intent="fact",
            graph_method="ego",
            entities=extract_entities_from_query(q),
            confidence=0.8,
            reason="命中精确实体/术语模式",
        )

    if any(p in q for p in SEMANTIC_PATTERNS):
        graph = any(p in q for p in ["架构", "框架", "模块", "上下游", "配合"])
        return RetrievalPlan(
            bm25=True,
            vector=True,
            graph=graph,
            bm25_top_k=6,
            vector_top_k=10,
            graph_top_k=8 if graph else 0,
            query_type="semantic",
            intent="optimize" if any(p in q for p in ["优化", "改进", "建议"]) else "explain",
            graph_method="subgraph" if graph else "none",
            confidence=0.65,
            reason="命中语义解释/优化模式",
        )

    return RetrievalPlan(
        bm25=True,
        vector=True,
        graph=True,
        bm25_top_k=6,
        vector_top_k=6,
        graph_top_k=6,
        graph_depth=1,
        query_type="default",
        intent="default",
        graph_method="ego",
        confidence=0.55,
        reason="默认混合检索",
    )


def should_use_llm(query: str, rule_plan: RetrievalPlan) -> bool:
    """判断是否需要 LLM 精判。"""
    q = query.strip()
    if rule_plan.intent == "chat":
        return False
    if len(q) <= 12 and rule_plan.intent in {"fact", "exact"}:
        return False
    if any(p in q for p in AMBIGUOUS_PATTERNS):
        return True
    if len(q) >= 25:
        return True
    intent_hits = sum([
        any(p in q for p in GLOBAL_PATTERNS),
        any(p in q for p in RELATION_PATTERNS),
        any(p in q for p in SEMANTIC_PATTERNS),
    ])
    if intent_hits >= 2:
        return True
    if rule_plan.confidence < 0.65:
        return True
    return rule_plan.graph_method in {"path", "subgraph"}


def route_by_llm(
    query: str,
    rule_plan: RetrievalPlan,
    context: str,
    templates: List[Dict[str, Any]],
    llm: Any = None,
) -> Dict[str, Any]:
    """调用 LLM Router 输出结构化路由结果。"""
    if llm is None:
        from llm.manager import llm_manager
        llm = llm_manager

    prompt = LLM_ROUTER_PROMPT.format(
        query=query,
        context=context or "无",
        templates=json.dumps(templates or [], ensure_ascii=False),
        rule_plan=json.dumps(rule_plan.to_dict(), ensure_ascii=False),
    )
    result = llm.complete_json(prompt, {})
    return result if isinstance(result, dict) else {}


def merge_rule_and_llm_plan(rule_plan: RetrievalPlan, llm_result: Dict[str, Any]) -> RetrievalPlan:
    """合并规则计划和 LLM 计划。"""
    confidence = _safe_float(llm_result.get("confidence"), 0.0)
    if confidence < 0.45:
        return rule_plan

    intent = str(llm_result.get("intent") or rule_plan.intent).strip()
    if intent not in INTENTS:
        intent = rule_plan.intent

    retrieval = llm_result.get("retrieval") or {}
    top_k = llm_result.get("top_k") or {}
    graph_method = str(llm_result.get("graph_method") or rule_plan.graph_method).strip()
    if graph_method not in GRAPH_METHODS:
        graph_method = rule_plan.graph_method

    if intent == "chat":
        return RetrievalPlan(
            bm25=False,
            vector=False,
            graph=False,
            query_type="chat",
            intent="chat",
            optimized_query=str(llm_result.get("optimized_query") or "").strip(),
            confidence=confidence,
            reason=str(llm_result.get("reason") or "LLM 判断为闲聊"),
        )

    bm25 = bool(retrieval.get("bm25", rule_plan.bm25))
    vector = bool(retrieval.get("vector", rule_plan.vector))
    graph = bool(retrieval.get("graph", rule_plan.graph))

    if rule_plan.bm25:
        bm25 = True
    if rule_plan.vector:
        vector = True
    if graph_method != "none":
        graph = True

    optimized_query = str(llm_result.get("optimized_query") or rule_plan.optimized_query).strip()
    expanded_queries = _string_list(llm_result.get("expanded_queries"), limit=3)
    entities = _string_list(llm_result.get("entities"), limit=8) or rule_plan.entities

    return RetrievalPlan(
        bm25=bm25,
        vector=vector,
        graph=graph,
        community=bool(retrieval.get("community", rule_plan.community)),
        bm25_top_k=_safe_int(top_k.get("bm25"), rule_plan.bm25_top_k),
        vector_top_k=_safe_int(top_k.get("vector"), rule_plan.vector_top_k),
        graph_top_k=_safe_int(top_k.get("graph"), rule_plan.graph_top_k),
        graph_depth=rule_plan.graph_depth if graph_method != "path" else max(rule_plan.graph_depth, 2),
        query_type=intent,
        intent=intent,
        optimized_query=optimized_query,
        expanded_queries=expanded_queries,
        entities=entities,
        graph_method=graph_method,
        confidence=confidence,
        reason=str(llm_result.get("reason") or "LLM 路由"),
    )


def extract_keywords(query: str) -> List[str]:
    """从查询中提取关键词，用于 BM25 检索"""
    keywords = []
    keywords.extend(re.findall(r"[A-Za-z][A-Za-z0-9_]*", query))
    keywords.extend(re.findall(r"[一-龥]{2,6}", query))
    keywords.extend(re.findall(r"\d+", query))

    seen = set()
    result = []
    for word in keywords:
        if word not in seen:
            seen.add(word)
            result.append(word)
    return result[:8]


def extract_entities_from_query(query: str) -> List[str]:
    """从查询中提取可能的实体名。"""
    entities = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)
    entities.extend(re.findall(r"[A-Z]{2,}", query))
    return _string_list(entities, limit=8)


def _retrieve_query_templates(query: str, llm: Any = None) -> List[Dict[str, Any]]:
    try:
        from services.query_templates import QueryTemplateService
        return QueryTemplateService(llm=llm).retrieve_templates(query, top_k=3)
    except Exception:
        return []


def _string_list(value: Any, limit: int) -> List[str]:
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _safe_int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default
