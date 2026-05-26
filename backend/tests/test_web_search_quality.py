"""
Web search ranking and verifier regression tests.

Run:
    PYTHONPATH=backend python backend/tests/test_web_search_quality.py
"""

from unittest.mock import patch

from agents.web_verifier import WebSearchVerifierAgent
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


if __name__ == "__main__":
    test_authoritative_results_rank_above_weak_results()
    test_dedupe_keeps_highest_quality_result()
    test_web_verifier_preserves_metadata_and_rejects_weak_empty_snippet()
    test_known_research_results_seed_authoritative_sources()
    print("=== Web search quality regression tests passed ===")
