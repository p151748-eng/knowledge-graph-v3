"""
AcademicSearchTool: 学术检索工具，优先使用 AI4Scholar，输出兼容 Web evidence 的结果。
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin

import httpx

from config import config
from tools.base import BaseTool
from tools.web_search import WebSearchTool


ACADEMIC_INTENTS = {
    "paper_search",
    "paper_match",
    "paper_detail",
    "paper_citations",
    "paper_references",
    "paper_recommendations",
    "paper_verify",
    "related_papers",
    "snippet_search",
    "author_search",
}


@dataclass
class AcademicSearchPlan:
    intent: str
    query: str
    paper_id: str = ""
    year: Optional[str] = None
    use_snippets: bool = False
    requires_lookup: bool = False
    reason: str = "规则路由"


ACADEMIC_ROUTER_PROMPT = """你是学术检索路由器，只判断应该调用哪类学术检索接口，不回答用户问题。

【用户问题】
{query}

可选 intent 只能是：paper_search, paper_match, paper_detail, paper_citations, paper_references, paper_recommendations, paper_verify, related_papers, snippet_search, author_search。

请输出 JSON：
{{
  "intent": "paper_search",
  "query": "用于检索的关键词或标题",
  "paper_id": "如果用户给出 DOI/ARXIV/Semantic Scholar ID 则填写，否则为空",
  "use_snippets": false,
  "reason": "简短理由"
}}
"""


class AcademicSearchRouter:
    """学术检索子路由：规则优先，LLM 兜底。"""

    def __init__(self, llm=None):
        self.llm = llm

    def route(self, query: str, year: Optional[str] = None) -> AcademicSearchPlan:
        query = (query or "").strip()
        lowered = query.lower()
        year = year or self._extract_year_filter(query)
        paper_id = self._extract_paper_id(query)

        if self._contains(lowered, ["真实", "真假", "是否存在", "是真的吗", "是否真实", "verify", "real paper", "exist"]):
            return AcademicSearchPlan("paper_verify", self._clean_query(query), paper_id, year, requires_lookup=not bool(paper_id), reason="用户请求验证论文真实性")
        if self._contains(lowered, ["相关论文", "类似论文", "相关文献", "参考论文", "related papers", "related work"]):
            return AcademicSearchPlan("related_papers", self._clean_query(query), paper_id, year, requires_lookup=not bool(paper_id), reason="用户请求相关论文参考")
        if self._contains(lowered, ["引用", "被引", "cited by", "citations", "citation"]):
            return AcademicSearchPlan("paper_citations", self._clean_query(query), paper_id, year, requires_lookup=not bool(paper_id), reason="用户询问引用/被引论文")
        if self._contains(lowered, ["参考文献", "参考了", "references", "reference list", "bibliography"]):
            return AcademicSearchPlan("paper_references", self._clean_query(query), paper_id, year, requires_lookup=not bool(paper_id), reason="用户询问参考文献")
        if self._contains(lowered, ["推荐", "类似", "相似", "similar", "recommend"]):
            return AcademicSearchPlan("paper_recommendations", self._clean_query(query), paper_id, year, requires_lookup=not bool(paper_id), reason="用户请求相似论文推荐")
        if self._contains(lowered, ["片段", "正文", "全文中", "论文中", "snippet", "text span"]):
            return AcademicSearchPlan("snippet_search", self._clean_query(query), paper_id, year, use_snippets=True, reason="用户请求论文正文片段")
        if self._contains(lowered, ["作者", "学者", "author", "researcher"]):
            return AcademicSearchPlan("author_search", self._clean_author_query(query), paper_id, year, reason="用户请求作者/学者检索")
        if paper_id or self._contains(lowered, ["详情", "元数据", "metadata", "detail"]):
            return AcademicSearchPlan("paper_detail", self._clean_query(query), paper_id, year, requires_lookup=not bool(paper_id), reason="用户请求论文详情")
        if self._contains(lowered, ["精确", "标题", "题名", "match", "exact"]):
            return AcademicSearchPlan("paper_match", self._clean_query(query), paper_id, year, reason="用户请求按标题精确匹配")

        llm_plan = self._route_with_llm(query, year)
        if llm_plan:
            return llm_plan
        return AcademicSearchPlan("paper_search", self._clean_query(query), paper_id, year, use_snippets=True, reason="默认论文关键词搜索")

    def _route_with_llm(self, query: str, year: Optional[str]) -> Optional[AcademicSearchPlan]:
        if not self.llm:
            return None
        try:
            data = self.llm.complete_json(ACADEMIC_ROUTER_PROMPT.format(query=query), {})
            intent = data.get("intent")
            if intent not in ACADEMIC_INTENTS:
                return None
            paper_id = data.get("paper_id") or self._extract_paper_id(query)
            return AcademicSearchPlan(
                intent=intent,
                query=data.get("query") or self._clean_query(query),
                paper_id=paper_id,
                year=year,
                use_snippets=bool(data.get("use_snippets")),
                requires_lookup=intent in {"paper_detail", "paper_citations", "paper_references", "paper_recommendations", "paper_verify", "related_papers"} and not bool(paper_id),
                reason=data.get("reason") or "LLM 路由",
            )
        except Exception:
            return None

    def _extract_paper_id(self, query: str) -> str:
        patterns = [
            r"ARXIV[:：]?\s*(\d{4}\.\d{4,5}(?:v\d+)?)",
            r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5}(?:v\d+)?)",
            r"DOI[:：]?\s*([^\s，,；;]+/[^\s，,；;]+)",
            r"PMID[:：]?\s*(\d+)",
            r"\b([a-f0-9]{40})\b",
            r"\b(\d{4}\.\d{4,5}(?:v\d+)?)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, query or "", re.I)
            if match:
                value = match.group(1).strip()
                if pattern.startswith("DOI"):
                    return f"DOI:{value}"
                if pattern.startswith("PMID"):
                    return f"PMID:{value}"
                return value
        return ""

    def _contains(self, lowered: str, terms: List[str]) -> bool:
        return any(term.lower() in lowered for term in terms)

    def _clean_query(self, query: str) -> str:
        cleaned = self._remove_search_instructions(query)
        cleaned = self._extract_best_query_segment(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ：:，,。")
        return self._limit_query_terms(cleaned) or (query or "")[:160]

    def _remove_search_instructions(self, query: str) -> str:
        cleaned = re.sub(r"\s*\|\|\s*", " || ", query or "")
        cleaned = re.sub(r"(联网|搜索|查询|查找|帮我|请|一下|可以|补充内容|最新|论文|文献)", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"(重点找|优先找|尤其是|围绕|关于|相关的|相关)", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"(研究现状|研究背景|相关工作|研究空白|参考论文|参考文献|依据|综述|开题)", " ", cleaned, flags=re.I)
        return cleaned

    def _extract_best_query_segment(self, text: str) -> str:
        parts = [part.strip() for part in re.split(r"\s+\|\|\s+|[。；;\n]", text or "") if part.strip()]
        if not parts:
            return text or ""
        return max(parts, key=self._segment_score)

    def _segment_score(self, text: str) -> float:
        lowered = text.lower()
        score = 0.0
        score += min(len(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)), 8) * 1.2
        score += min(len(re.findall(r"[一-龥]{2,8}", text)), 6) * 0.8
        score += sum(2.0 for term in ["rag", "retrieval", "augmented", "multi-agent", "agent", "llm", "medical", "biomedical", "clinical"] if term in lowered)
        score -= max(0, len(text) - 140) / 40
        return score

    def _limit_query_terms(self, text: str, max_terms: int = 12, max_chars: int = 160) -> str:
        tokens = re.findall(r'"[^"]+"|[A-Za-z][A-Za-z0-9_-]{2,}|[一-龥]{2,8}|\d{4}', text or "")
        stopwords = {
            "帮我", "请你", "可以", "一下", "这个", "该选题", "选题", "内容", "重点", "优先", "研究", "分析",
            "find", "search", "paper", "papers", "latest", "related", "about", "with", "using",
        }
        selected = []
        seen = set()
        for token in tokens:
            normalized = token.strip('"').lower()
            if normalized in stopwords or token in stopwords:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            selected.append(token)
            if len(selected) >= max_terms:
                break
        limited = " ".join(selected) if selected else (text or "")
        return limited[:max_chars].strip()

    def _extract_year_filter(self, query: str) -> Optional[str]:
        lowered = (query or "").lower()
        after_match = re.search(r"(20\d{2})\s*年?\s*(以后|以来|之后|及以后|至今|以降|后|after|since)", lowered)
        if not after_match:
            after_match = re.search(r"(after|since)\s+(20\d{2})", lowered)
        if after_match:
            start = int(after_match.group(1) if after_match.group(1).isdigit() else after_match.group(2))
            return f"{start}-2026"
        range_match = re.search(r"(20\d{2})\s*[-—~至到]\s*(20\d{2})", lowered)
        if range_match:
            return f"{range_match.group(1)}-{range_match.group(2)}"
        return None

    def _clean_author_query(self, query: str) -> str:
        cleaned = re.sub(r"(搜索|查询|查找|作者|学者|的论文|论文|author|researcher)", " ", query or "", flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ：:，,。")
        return cleaned or self._clean_query(query)


class AI4ScholarClient:
    """AI4Scholar Open Platform client."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key if api_key is not None else config.AI4SCHOLAR_API_KEY
        self.base_url = (base_url or config.AI4SCHOLAR_BASE_URL).rstrip("/")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(config.AI4SCHOLAR_ENABLED and self.api_key and self.base_url)

    def search_semantic(self, query: str, year: Optional[str] = None, max_results: int = 10) -> List[Dict[str, Any]]:
        params = {
            "query": query,
            "limit": max_results,
            "fields": "paperId,url,title,authors,year,abstract,citationCount,openAccessPdf,venue,publicationDate",
        }
        if year:
            params["publicationDateOrYear"] = year.replace("-", ":") if re.match(r"^\d{4}-\d{4}$", year) else year
        return self._get("/graph/v1/paper/search", params)

    def search_arxiv(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        params = {
            "query": f"{query} arxiv",
            "limit": max_results,
            "fields": "paperId,url,title,authors,year,abstract,citationCount,openAccessPdf,externalIds",
            "openAccessPdf": "true",
        }
        return self._get("/graph/v1/paper/search", params)

    def search_match(self, query: str) -> List[Dict[str, Any]]:
        params = {
            "query": query,
            "fields": "paperId,url,title,authors,year,abstract,citationCount,openAccessPdf,venue,publicationDate,externalIds",
        }
        return self._get("/graph/v1/paper/search/match", params)

    def get_paper_detail(self, paper_id: str) -> List[Dict[str, Any]]:
        fields = "paperId,url,title,authors,year,abstract,citationCount,openAccessPdf,venue,publicationDate,externalIds"
        return self._get(f"/graph/v1/paper/{quote(paper_id, safe='')}", {"fields": fields})

    def get_paper_citations(self, paper_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        fields = "contexts,intents,isInfluential,paperId,url,title,authors,year,abstract,citationCount,openAccessPdf,venue"
        return self._get(f"/graph/v1/paper/{quote(paper_id, safe='')}/citations", {"limit": limit, "fields": fields})

    def get_paper_references(self, paper_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        fields = "contexts,intents,isInfluential,paperId,url,title,authors,year,abstract,citationCount,openAccessPdf,venue"
        return self._get(f"/graph/v1/paper/{quote(paper_id, safe='')}/references", {"limit": limit, "fields": fields})

    def get_paper_recommendations(self, paper_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        fields = "paperId,url,title,authors,year,abstract,citationCount,openAccessPdf,venue"
        return self._get(f"/recommendations/v1/papers/forpaper/{quote(paper_id, safe='')}", {"limit": limit, "fields": fields})

    def search_authors(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self._get("/graph/v1/author/search", {"query": query, "limit": limit, "fields": "authorId,name,url,affiliations,paperCount,citationCount,hIndex"})

    def search_semantic_snippets(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self._get("/graph/v1/snippet/search", {"query": query, "limit": limit})

    def _get(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.available:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = httpx.get(urljoin(self.base_url + "/", path.lstrip("/")), params=params, headers=headers, timeout=self.timeout, trust_env=False)
        response.raise_for_status()
        return self._extract_items(response.json())

    def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.available:
            return []
        payload = {"tool": tool_name, "arguments": arguments, "parameters": arguments}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Key": self.api_key or "",
            "Content-Type": "application/json",
        }
        for path in (f"/mcp/tools/{tool_name}", f"/tools/{tool_name}", "/mcp/call", "/api/mcp/call", "/api/tools/call"):
            try:
                response = httpx.post(urljoin(self.base_url + "/", path.lstrip("/")), json=payload, headers=headers, timeout=self.timeout)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                parsed = response.json()
                return self._extract_items(parsed)
            except Exception:
                continue
        return []

    def _extract_items(self, data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("results", "papers", "data", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            if any(key in data for key in ("paperId", "title", "authorId", "name")):
                return [data]
            content = data.get("content")
            if isinstance(content, list):
                items = []
                for block in content:
                    text = block.get("text") if isinstance(block, dict) else None
                    if not text:
                        continue
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        continue
                    items.extend(self._extract_items(parsed))
                return items
        return []


class AcademicSearchTool(BaseTool):
    """学术检索工具"""

    name = "academic_search"
    description = "通过 AI4Scholar 检索学术论文并返回可引用证据"

    def __init__(self, db=None, client: Optional[AI4ScholarClient] = None, llm=None):
        self.db = db
        self.client = client or AI4ScholarClient()
        self.llm = llm
        self.router = AcademicSearchRouter(llm)

    def execute(self, query: str, max_results: int = 5, year: Optional[str] = None, use_snippets: Optional[bool] = None, **kwargs) -> Dict[str, Any]:
        max_results = max_results or config.ACADEMIC_SEARCH_MAX_RESULTS
        plan = self.router.route(query, year=year)
        if use_snippets is not None:
            plan.use_snippets = use_snippets
        elif plan.intent == "paper_search":
            plan.use_snippets = config.ACADEMIC_SEARCH_USE_SNIPPETS
        diagnostics: Dict[str, Any] = {
            "provider": "ai4scholar",
            "queries": self._expand_queries(plan.query),
            "fallback": False,
            "errors": [],
            "academic_intent": plan.intent,
            "endpoint": self._endpoint_for_intent(plan.intent),
            "requires_lookup": plan.requires_lookup,
            "resolved_paper_id": plan.paper_id,
            "reason": plan.reason,
        }
        results: List[Dict[str, Any]] = []

        if self.client.available:
            try:
                results = self._execute_plan(plan, diagnostics, max_results)
            except Exception as exc:
                diagnostics["errors"].append(f"{plan.intent}: {exc}")
        else:
            diagnostics["errors"].append("AI4Scholar is disabled or missing API key/base URL")

        ranked = self._rank_and_dedupe(results)
        if plan.intent in {"paper_verify", "related_papers"}:
            ranked = results
        if not ranked and config.ACADEMIC_SEARCH_FALLBACK_WEB:
            diagnostics["fallback"] = True
            fallback = WebSearchTool(self.db).execute(query, max_results=max_results, save=False)
            ranked = [self._from_web_result(item) for item in fallback.get("results", [])]

        return {"results": ranked[:max_results], "diagnostics": diagnostics, "provider": "academic_search"}

    def _execute_plan(self, plan: AcademicSearchPlan, diagnostics: Dict[str, Any], max_results: int) -> List[Dict[str, Any]]:
        if plan.intent == "paper_search":
            return self._execute_paper_search(plan, diagnostics, max_results)
        if plan.intent == "paper_match":
            return self._normalize_many(self.client.search_match(plan.query), plan.query, "semantic_match")
        if plan.intent == "snippet_search":
            return self._normalize_many(self.client.search_semantic_snippets(plan.query, limit=max_results), plan.query, "semantic_snippet")
        if plan.intent == "author_search":
            return self._normalize_many(self.client.search_authors(plan.query, limit=max_results), plan.query, "semantic_author")
        if plan.intent in {"paper_verify", "related_papers"}:
            return self._execute_verify_related(plan, diagnostics, max_results)

        paper_id = plan.paper_id or self._resolve_paper_id(plan.query, diagnostics)
        diagnostics["resolved_paper_id"] = paper_id
        if not paper_id:
            return self._execute_paper_search(plan, diagnostics, max_results)

        if plan.intent == "paper_detail":
            return self._normalize_many(self.client.get_paper_detail(paper_id), plan.query, "semantic_detail")
        if plan.intent == "paper_citations":
            return self._normalize_many(self.client.get_paper_citations(paper_id, limit=max_results), plan.query, "semantic_citations")
        if plan.intent == "paper_references":
            return self._normalize_many(self.client.get_paper_references(paper_id, limit=max_results), plan.query, "semantic_references")
        if plan.intent == "paper_recommendations":
            return self._normalize_many(self.client.get_paper_recommendations(paper_id, limit=max_results), plan.query, "semantic_recommendations")
        return self._execute_paper_search(plan, diagnostics, max_results)

    def _execute_verify_related(self, plan: AcademicSearchPlan, diagnostics: Dict[str, Any], max_results: int) -> List[Dict[str, Any]]:
        paper_id = plan.paper_id or self._resolve_paper_id(plan.query, diagnostics)
        diagnostics["resolved_paper_id"] = paper_id
        if not paper_id:
            diagnostics.update({
                "verification_status": "unverified",
                "verification_confidence": 0.2,
                "verification_reasons": ["未检索到稳定 paper_id"],
            })
            return self._execute_paper_search(plan, diagnostics, max_results)

        detail = self._normalize_many(self.client.get_paper_detail(paper_id), plan.query, "semantic_detail")
        original = detail[0] if detail else {"paper_id": paper_id, "title": plan.query, "source": "semantic_detail"}
        original["relation"] = "original"
        verification = self._verify_paper(original, plan.query)
        diagnostics.update({
            "verification_status": verification["status"],
            "verification_confidence": verification["confidence"],
            "verification_reasons": verification["reasons"],
        })

        related: List[Dict[str, Any]] = [original]
        related.extend(self._related_group(lambda: self.client.get_paper_references(paper_id, limit=max_results), plan.query, "semantic_references", "reference", diagnostics))
        related.extend(self._related_group(lambda: self.client.get_paper_citations(paper_id, limit=max_results), plan.query, "semantic_citations", "citation", diagnostics))
        recommendations = self._related_group(lambda: self.client.get_paper_recommendations(paper_id, limit=max_results), plan.query, "semantic_recommendations", "recommendation", diagnostics)
        if not recommendations:
            recommendations = self._search_related_by_title(original, diagnostics, max_results)
        related.extend(recommendations)
        return related

    def _related_group(self, fetch, query: str, source: str, relation: str, diagnostics: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            items = self._normalize_many(fetch(), query, source)
        except Exception as exc:
            diagnostics["errors"].append(f"{relation}: {exc}")
            return []
        for item in items:
            item["relation"] = relation
        return self._rank_and_dedupe(items)

    def _search_related_by_title(self, original: Dict[str, Any], diagnostics: Dict[str, Any], max_results: int) -> List[Dict[str, Any]]:
        query = " ".join(part for part in [original.get("title", ""), original.get("snippet", "")[:160]] if part).strip()
        if not query:
            return []
        try:
            items = self._normalize_many(self.client.search_semantic(query, max_results=max_results), query, "semantic_related_search")
        except Exception as exc:
            diagnostics["errors"].append(f"related_search: {exc}")
            return []
        original_id = (original.get("paper_id") or "").lower()
        related = []
        for item in self._rank_and_dedupe(items):
            if original_id and (item.get("paper_id") or "").lower() == original_id:
                continue
            item["relation"] = "search_related"
            related.append(item)
        return related

    def _verify_paper(self, paper: Dict[str, Any], query: str) -> Dict[str, Any]:
        reasons = []
        confidence = 0.25
        if paper.get("paper_id"):
            confidence += 0.3
            reasons.append("检索到稳定 paper_id")
        if paper.get("url"):
            confidence += 0.2
            reasons.append("检索到权威论文 URL")
        if paper.get("authors"):
            confidence += 0.1
            reasons.append("检索到作者信息")
        if paper.get("year"):
            confidence += 0.08
            reasons.append("检索到发表年份")
        if paper.get("snippet"):
            confidence += 0.07
            reasons.append("检索到摘要或论文片段")
        if self._title_similarity(query, paper.get("title", "")) >= 0.55:
            confidence += 0.12
            reasons.append("标题与用户输入较匹配")
        confidence = round(min(confidence, 0.98), 3)
        if confidence >= 0.75:
            status = "verified"
        elif confidence >= 0.5:
            status = "likely"
        else:
            status = "unverified"
        return {"status": status, "confidence": confidence, "reasons": reasons or ["未检索到足够元数据"]}

    def _title_similarity(self, query: str, title: str) -> float:
        query_tokens = set(re.findall(r"[a-z0-9]+|[一-龥]{2,}", (query or "").lower()))
        title_tokens = set(re.findall(r"[a-z0-9]+|[一-龥]{2,}", (title or "").lower()))
        if not query_tokens or not title_tokens:
            return 0.0
        return len(query_tokens & title_tokens) / len(title_tokens)

    def _execute_paper_search(self, plan: AcademicSearchPlan, diagnostics: Dict[str, Any], max_results: int) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for search_query in diagnostics["queries"]:
            try:
                semantic = self.client.search_semantic(search_query, year=plan.year, max_results=max_results)
                results.extend(self._normalize_many(semantic, search_query, "semantic_scholar"))
            except Exception as exc:
                diagnostics["errors"].append(f"search_semantic: {exc}")
            try:
                arxiv = self.client.search_arxiv(search_query, max_results=max_results)
                results.extend(self._normalize_many(arxiv, search_query, "arxiv"))
            except Exception as exc:
                diagnostics["errors"].append(f"search_arxiv: {exc}")
            if plan.use_snippets:
                try:
                    snippets = self.client.search_semantic_snippets(search_query, limit=max_results)
                    results.extend(self._normalize_many(snippets, search_query, "semantic_snippet"))
                except Exception as exc:
                    diagnostics["errors"].append(f"search_semantic_snippets: {exc}")
        return results

    def _resolve_paper_id(self, query: str, diagnostics: Dict[str, Any]) -> str:
        clean_query = self._strip_relation_words(query)
        candidates: List[Dict[str, Any]] = []
        try:
            candidates.extend(self._normalize_many(self.client.search_match(clean_query), clean_query, "semantic_match"))
        except Exception as exc:
            diagnostics["errors"].append(f"resolve_match: {exc}")
        try:
            candidates.extend(self._normalize_many(self.client.search_semantic(clean_query, max_results=3), clean_query, "semantic_scholar"))
        except Exception as exc:
            diagnostics["errors"].append(f"resolve_search: {exc}")
        ranked = self._rank_and_dedupe(candidates)
        return ranked[0].get("paper_id", "") if ranked else ""

    def _strip_relation_words(self, query: str) -> str:
        cleaned = re.sub(r"(这篇|帮我|查找|找|返回|并返回|是否真实|是否存在|是真的吗|是真是假|真实|真假|相关论文参考|相关论文|相关文献|参考论文|引用了哪些|引用|被引|参考文献有哪些|参考文献|参考|参考了哪些|推荐类似|推荐|类似|相似|的论文|论文|文献|有哪些|哪一些|verify|real paper|exist|related papers|related work|citations?|cited by|references?|recommendations?|similar)", " ", query or "", flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ：:，,。")
        return cleaned or query

    def _endpoint_for_intent(self, intent: str) -> str:
        return {
            "paper_search": "/graph/v1/paper/search",
            "paper_match": "/graph/v1/paper/search/match",
            "paper_detail": "/graph/v1/paper/{paper_id}",
            "paper_citations": "/graph/v1/paper/{paper_id}/citations",
            "paper_references": "/graph/v1/paper/{paper_id}/references",
            "paper_recommendations": "/recommendations/v1/papers/forpaper/{paper_id}",
            "paper_verify": "/graph/v1/paper/search/match + related endpoints",
            "related_papers": "/graph/v1/paper/search/match + related endpoints",
            "snippet_search": "/graph/v1/snippet/search",
            "author_search": "/graph/v1/author/search",
        }.get(intent, "/graph/v1/paper/search")

    def _expand_queries(self, query: str) -> List[str]:
        normalized = re.sub(r"\s+", " ", query or "").strip()
        if not normalized:
            return []
        if " || " in normalized:
            queries = []
            seen = set()
            for item in (part.strip() for part in normalized.split(" || ") if part.strip()):
                compact = self.router._clean_query(item)
                key = compact.lower()
                if key and key not in seen:
                    seen.add(key)
                    queries.append(compact)
            return queries[:6]
        return [self.router._clean_query(normalized)]

    def _normalize_many(self, items: List[Dict[str, Any]], query: str, source: str) -> List[Dict[str, Any]]:
        return [item for item in (self._normalize(item, query, source, index) for index, item in enumerate(items or [])) if item]

    def _normalize(self, item: Dict[str, Any], query: str, source: str, index: int) -> Dict[str, Any]:
        if "paper" in item and isinstance(item.get("paper"), dict):
            item = {**item, **item["paper"]}
        title = self._pick(item, "title", "paper_title", "name")
        snippet = self._pick(item, "abstract", "snippet", "summary", "text", "content")
        if not snippet:
            snippet = self._citation_context(item)
        url = self._pick(item, "url", "paper_url", "pdf_url", "external_url") or self._open_access_url(item)
        paper_id = self._pick(item, "paperId", "paper_id", "id", "arxiv_id", "pmid", "doi", "authorId", "author_id")
        if not url:
            url = self._url_from_identifiers(item, source, paper_id)
        if not title and not snippet:
            return {}
        authors = item.get("authors", [])
        if isinstance(authors, list):
            authors = ", ".join(author.get("name", str(author)) if isinstance(author, dict) else str(author) for author in authors[:8])
        year = self._pick(item, "year", "publicationYear", "published", "published_date")
        return {
            "title": title or "未命名论文",
            "url": url,
            "snippet": snippet or "",
            "authors": authors or "",
            "year": year or "",
            "source": source,
            "provider": "ai4scholar",
            "paper_id": paper_id or "",
            "result_type": "web_evidence",
            "type": "web",
            "rank": index + 1,
            "query": query,
            "quality_score": self._quality_score(title, snippet, url, source),
        }

    def _pick(self, item: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if value is None:
                continue
            if isinstance(value, (str, int, float)):
                return str(value)
        return ""

    def _open_access_url(self, item: Dict[str, Any]) -> str:
        open_access_pdf = item.get("openAccessPdf")
        if isinstance(open_access_pdf, dict):
            return self._pick(open_access_pdf, "url")
        return ""

    def _citation_context(self, item: Dict[str, Any]) -> str:
        contexts = item.get("contexts")
        if isinstance(contexts, list):
            return " ".join(str(context) for context in contexts[:3])
        return ""

    def _url_from_identifiers(self, item: Dict[str, Any], source: str, paper_id: str) -> str:
        arxiv_id = self._pick(item, "arxivId", "arxiv_id") or (paper_id if re.match(r"^\d{4}\.\d{4,5}", paper_id or "") else "")
        doi = self._pick(item, "doi", "DOI")
        if arxiv_id:
            return f"https://arxiv.org/abs/{arxiv_id}"
        if doi:
            return f"https://doi.org/{doi.replace('DOI:', '')}"
        if source == "semantic_author" and paper_id:
            return f"https://www.semanticscholar.org/author/{paper_id}"
        if source.startswith("semantic") and paper_id:
            return f"https://www.semanticscholar.org/paper/{paper_id}"
        return ""

    def _quality_score(self, title: str, snippet: str, url: str, source: str) -> float:
        score = 0.55
        if title:
            score += 0.12
        if snippet:
            score += min(0.18, len(snippet) / 1000)
        if url:
            score += 0.08
        if source == "semantic_scholar":
            score += 0.08
        elif source == "arxiv":
            score += 0.07
        elif source == "semantic_snippet":
            score += 0.05
        return round(min(score, 0.98), 3)

    def _rank_and_dedupe(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            key = (item.get("paper_id") or item.get("url") or item.get("title") or "").lower()
            if not key:
                continue
            existing = deduped.get(key)
            if not existing or item.get("quality_score", 0) > existing.get("quality_score", 0):
                deduped[key] = item
        return sorted(deduped.values(), key=lambda item: (-float(item.get("quality_score", 0)), item.get("rank", 99)))

    def _from_web_result(self, item: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(item)
        enriched.setdefault("source", "web_search")
        enriched.setdefault("result_type", "web_evidence")
        enriched.setdefault("type", "web")
        return enriched
