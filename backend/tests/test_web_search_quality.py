"""
Web search ranking and verifier regression tests.

Run:
    PYTHONPATH=backend python backend/tests/test_web_search_quality.py
"""

from unittest.mock import patch

from agents.web_verifier import WebSearchVerifierAgent
from tools.academic_search import AcademicSearchRouter, AcademicSearchTool
from tools.web_search import WebSearchTool


class FakeLLM:
    def complete_json(self, prompt, json_schema):
        raise ValueError("force heuristic fallback")


def test_authoritative_results_rank_above_weak_results():
    tool = WebSearchTool(db=None)
    results = [
        {
            "title": "GraphRAG Microsoft paper - 360翻译",
            "url": "https://fanyi.so.com/?src=onebox#graphrag",
            "snippet": "",
            "provider": "so",
            "rank": 1,
        },
        {
            "title": "GraphRAG: From Local to Global Search",
            "url": "https://www.microsoft.com/en-us/research/project/graphrag/",
            "snippet": "Microsoft Research GraphRAG combines graph indexing with local and global search.",
            "provider": "bing_cn",
            "rank": 2,
        },
    ]
    for item in results:
        item["quality_score"] = tool._quality_score(item, "GraphRAG Microsoft paper")
    ranked = tool._rank_and_dedupe(results)
    assert "microsoft.com" in ranked[0]["url"]
    assert ranked[0]["quality_score"] > ranked[1]["quality_score"]


def test_dedupe_keeps_highest_quality_result():
    tool = WebSearchTool(db=None)
    results = [
        {
            "title": "Self-RAG paper",
            "url": "https://arxiv.org/abs/2310.11511",
            "snippet": "",
            "provider": "so",
            "rank": 1,
            "quality_score": 0.4,
        },
        {
            "title": "Self-RAG: Learning to Retrieve, Generate, and Critique",
            "url": "https://arxiv.org/abs/2310.11511",
            "snippet": "Self-RAG learns to retrieve, generate, and critique through self-reflection.",
            "provider": "bing_cn",
            "rank": 2,
            "quality_score": 0.9,
        },
    ]
    ranked = tool._rank_and_dedupe(results)
    assert len(ranked) == 1
    assert ranked[0]["quality_score"] == 0.9
    assert "Critique" in ranked[0]["title"]


def test_web_verifier_preserves_metadata_and_rejects_weak_empty_snippet():
    verifier = WebSearchVerifierAgent(db=None, llm=FakeLLM(), min_score=0.7)
    with patch("agents.web_verifier.WebSearchTool.execute", return_value={
        "results": [
            {
                "title": "GraphRAG Microsoft paper - 360翻译",
                "url": "https://fanyi.so.com/?src=onebox#graphrag",
                "snippet": "",
                "provider": "so",
                "rank": 1,
                "quality_score": 0.2,
            },
            {
                "title": "GraphRAG: From Local to Global Search",
                "url": "https://www.microsoft.com/en-us/research/project/graphrag/",
                "snippet": "GraphRAG uses graph-based indexing for global and local search.",
                "provider": "bing_cn",
                "rank": 2,
                "quality_score": 0.92,
            },
        ]
    }):
        with patch("agents.web_verifier.AcademicSearchTool.execute", return_value={"results": []}):
            accepted = verifier.search_and_grade("GraphRAG Microsoft paper", max_results=3)
    assert len(accepted) == 1
    assert accepted[0]["provider"] == "bing_cn"
    assert accepted[0]["quality_score"] == 0.92
    assert "microsoft.com" in accepted[0]["url"]


def test_known_research_results_seed_authoritative_sources():
    tool = WebSearchTool(db=None)
    self_rag = tool._known_research_results("Self-RAG Asai 2023")
    crag = tool._known_research_results("CRAG Corrective Retrieval Augmented Generation paper")
    graphrag = tool._known_research_results("GraphRAG Microsoft paper")
    assert any("arxiv.org/abs/2310.11511" in item["url"] for item in self_rag)
    assert any("arxiv.org/abs/2401.15884" in item["url"] for item in crag)
    assert any("microsoft.com" in item["url"] for item in graphrag)


def test_academic_query_prefers_ai4scholar_results():
    verifier = WebSearchVerifierAgent(db=None, llm=FakeLLM(), min_score=0.7)
    with patch("agents.web_verifier.AcademicSearchTool.execute", return_value={
        "results": [
            {
                "title": "Large Language Model based Multi-Agents: A Survey",
                "url": "https://arxiv.org/abs/2402.01680",
                "snippet": "Survey of LLM-based multi-agent systems and communication.",
                "provider": "ai4scholar",
                "source": "semantic_scholar",
                "paper_id": "ARXIV:2402.01680",
                "authors": "Example Author",
                "year": "2024",
                "quality_score": 0.94,
            }
        ]
    }) as academic_execute:
        with patch("agents.web_verifier.WebSearchTool.execute") as web_execute:
            accepted = verifier.search_and_grade("multi-agent communication protocol paper", max_results=3)
    academic_execute.assert_called_once()
    web_execute.assert_not_called()
    assert len(accepted) == 1
    assert accepted[0]["provider"] == "ai4scholar"
    assert accepted[0]["source"] == "semantic_scholar"
    assert accepted[0]["paper_id"] == "ARXIV:2402.01680"


def test_academic_query_falls_back_to_web_when_empty():
    verifier = WebSearchVerifierAgent(db=None, llm=FakeLLM(), min_score=0.7)
    with patch("agents.web_verifier.AcademicSearchTool.execute", return_value={"results": []}):
        with patch("agents.web_verifier.WebSearchTool.execute", return_value={
            "results": [
                {
                    "title": "GraphRAG: From Local to Global Search",
                    "url": "https://www.microsoft.com/en-us/research/project/graphrag/",
                    "snippet": "GraphRAG uses graph-based indexing for global and local search.",
                    "provider": "bing_cn",
                    "rank": 2,
                    "quality_score": 0.92,
                },
            ]
        }) as web_execute:
            accepted = verifier.search_and_grade("GraphRAG paper", max_results=3)
    web_execute.assert_called_once()
    assert len(accepted) == 1
    assert accepted[0]["provider"] == "bing_cn"


def test_academic_search_normalizes_ai4scholar_fields():
    tool = AcademicSearchTool(db=None)
    item = tool._normalize({
        "title": "Test Paper",
        "abstract": "This paper studies agent communication.",
        "paperId": "abc123",
        "authors": [{"name": "A"}, {"name": "B"}],
        "year": 2024,
    }, "agent communication", "semantic_scholar", 0)
    assert item["provider"] == "ai4scholar"
    assert item["source"] == "semantic_scholar"
    assert item["paper_id"] == "abc123"
    assert item["authors"] == "A, B"
    assert "semanticscholar.org" in item["url"]


def test_academic_router_maps_user_questions_to_intents():
    router = AcademicSearchRouter()
    cases = [
        ("这篇 Self-RAG 论文引用了哪些论文", "paper_citations"),
        ("Self-RAG 的参考文献有哪些", "paper_references"),
        ("推荐类似 Q-KVComm 的论文", "paper_recommendations"),
        ("搜索论文正文中关于 agent communication protocol 的片段", "snippet_search"),
        ("搜索学者 Yann LeCun 的论文", "author_search"),
        ("精确匹配标题 Self-RAG: Learning to Retrieve", "paper_match"),
    ]
    for query, intent in cases:
        assert router.route(query).intent == intent


def test_academic_search_dispatches_citations_after_lookup():
    class FakeClient:
        available = True

        def search_match(self, query):
            return [{"title": "Self-RAG", "paperId": "paper-1", "abstract": "A paper."}]

        def get_paper_citations(self, paper_id, limit=10):
            assert paper_id == "paper-1"
            return [{"paper": {"title": "Citation Paper", "paperId": "paper-2", "abstract": "Cites Self-RAG."}}]

    tool = AcademicSearchTool(db=None, client=FakeClient())
    result = tool.execute("Self-RAG 引用了哪些论文", max_results=3)
    assert result["diagnostics"]["academic_intent"] == "paper_citations"
    assert result["diagnostics"]["resolved_paper_id"] == "paper-1"
    assert result["diagnostics"]["endpoint"] == "/graph/v1/paper/{paper_id}/citations"
    assert result["results"][0]["title"] == "Citation Paper"


def test_academic_search_dispatches_author_search():
    class FakeClient:
        available = True

        def search_authors(self, query, limit=10):
            return [{"name": "Yann LeCun", "authorId": "123", "paperCount": 500}]

    tool = AcademicSearchTool(db=None, client=FakeClient())
    result = tool.execute("搜索学者 Yann LeCun 的论文", max_results=3)
    assert result["diagnostics"]["academic_intent"] == "author_search"
    assert result["diagnostics"]["endpoint"] == "/graph/v1/author/search"
    assert result["results"][0]["title"] == "Yann LeCun"
    assert "semanticscholar.org/author/123" in result["results"][0]["url"]


def test_academic_search_dispatches_snippet_search():
    class FakeClient:
        available = True

        def search_semantic_snippets(self, query, limit=10):
            return [{"title": "Snippet Paper", "snippet": "agent communication protocol appears in this span", "paperId": "paper-3"}]

    tool = AcademicSearchTool(db=None, client=FakeClient())
    result = tool.execute("搜索论文正文中关于 agent communication protocol 的片段", max_results=3)
    assert result["diagnostics"]["academic_intent"] == "snippet_search"
    assert result["diagnostics"]["endpoint"] == "/graph/v1/snippet/search"
    assert result["results"][0]["source"] == "semantic_snippet"


def test_academic_router_maps_verify_and_related_intents():
    router = AcademicSearchRouter()
    assert router.route("这篇 Self-RAG 论文是否真实").intent == "paper_verify"
    assert router.route("帮我找 Self-RAG 的相关论文参考").intent == "related_papers"


def test_academic_search_verifies_paper_and_returns_related_groups():
    class FakeClient:
        available = True

        def search_match(self, query):
            return [{"title": "Self-RAG", "paperId": "paper-1", "abstract": "A retrieval paper."}]

        def search_semantic(self, query, year=None, max_results=10):
            return []

        def get_paper_detail(self, paper_id):
            return [{"title": "Self-RAG", "paperId": paper_id, "abstract": "A retrieval paper.", "authors": [{"name": "A"}], "year": 2023, "url": "https://arxiv.org/abs/2310.11511"}]

        def get_paper_references(self, paper_id, limit=10):
            return [{"paper": {"title": "Reference Paper", "paperId": "ref-1", "abstract": "Prior work."}}]

        def get_paper_citations(self, paper_id, limit=10):
            return [{"paper": {"title": "Citation Paper", "paperId": "cit-1", "abstract": "Follow-up work."}}]

        def get_paper_recommendations(self, paper_id, limit=10):
            return [{"title": "Similar Paper", "paperId": "rec-1", "abstract": "Related work."}]

    tool = AcademicSearchTool(db=None, client=FakeClient())
    result = tool.execute("这篇 Self-RAG 论文是否真实，并返回相关论文参考", max_results=5)
    relations = {item.get("relation") for item in result["results"]}
    assert result["diagnostics"]["academic_intent"] == "paper_verify"
    assert result["diagnostics"]["verification_status"] == "verified"
    assert result["diagnostics"]["resolved_paper_id"] == "paper-1"
    assert {"original", "reference", "citation", "recommendation"}.issubset(relations)


def test_related_papers_falls_back_to_search_related_when_recommendations_empty():
    class FakeClient:
        available = True

        def search_match(self, query):
            return [{"title": "Self-RAG", "paperId": "paper-1", "abstract": "A retrieval paper."}]

        def search_semantic(self, query, year=None, max_results=10):
            if "retrieval paper" in query.lower():
                return [{"title": "Fallback Related", "paperId": "rel-1", "abstract": "Related by search."}]
            return []

        def get_paper_detail(self, paper_id):
            return [{"title": "Self-RAG", "paperId": paper_id, "abstract": "A retrieval paper.", "url": "https://arxiv.org/abs/2310.11511"}]

        def get_paper_references(self, paper_id, limit=10):
            return []

        def get_paper_citations(self, paper_id, limit=10):
            return []

        def get_paper_recommendations(self, paper_id, limit=10):
            return []

    tool = AcademicSearchTool(db=None, client=FakeClient())
    result = tool.execute("帮我找 Self-RAG 的相关论文参考", max_results=2)
    assert result["diagnostics"]["academic_intent"] == "related_papers"
    assert any(item.get("relation") == "search_related" for item in result["results"])


if __name__ == "__main__":
    test_authoritative_results_rank_above_weak_results()
    test_dedupe_keeps_highest_quality_result()
    test_web_verifier_preserves_metadata_and_rejects_weak_empty_snippet()
    test_known_research_results_seed_authoritative_sources()
    test_academic_query_prefers_ai4scholar_results()
    test_academic_query_falls_back_to_web_when_empty()
    test_academic_search_normalizes_ai4scholar_fields()
    test_academic_router_maps_user_questions_to_intents()
    test_academic_search_dispatches_citations_after_lookup()
    test_academic_search_dispatches_author_search()
    test_academic_search_dispatches_snippet_search()
    test_academic_router_maps_verify_and_related_intents()
    test_academic_search_verifies_paper_and_returns_related_groups()
    test_related_papers_falls_back_to_search_related_when_recommendations_empty()
    print("=== Web search quality regression tests passed ===")
