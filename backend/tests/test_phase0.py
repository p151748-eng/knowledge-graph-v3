"""阶段0验收测试脚本"""
import httpx
import json

BASE = "http://localhost:8003/api"
_client = httpx.Client(base_url=BASE, timeout=30.0, trust_env=False)


def test_health():
    r = _client.get("/health")
    data = r.json()
    assert data["success"] is True
    assert data["data"]["database"] == "connected"
    print("[PASS] /api/health - 数据库连接正常")


def test_ingest():
    r = _client.post(
        "/ingest",
        json={
            "title": "RAG技术概述",
            "content": "RAG是检索增强生成技术，依赖于向量数据库和LLM",
            "source": "test",
        },
    )
    data = r.json()
    assert data["success"] is True
    assert data["data"]["document_id"] > 0
    print(f"[PASS] /api/ingest - 文档导入成功，ID={data['data']['document_id']}")


def test_docs_list():
    r = _client.get("/docs")
    data = r.json()
    assert data["success"] is True
    assert data["data"]["total"] > 0
    print(f"[PASS] /api/docs - 文档列表获取成功，共{data['data']['total']}篇")


def test_kg_nodes():
    r = _client.get("/kg/nodes")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] /api/kg/nodes - 节点列表获取成功，共{data['data']['total']}个")


def test_kg_create_node():
    r = _client.post(
        "/kg/nodes",
        json={"name": "测试节点", "type": "entity", "description": "验收测试创建的节点"},
    )
    data = r.json()
    assert data["success"] is True
    assert data["data"]["id"] > 0
    print(f"[PASS] /api/kg/nodes - 节点创建成功，ID={data['data']['id']}")
    return data["data"]["id"]


def test_kg_graph():
    r = _client.get("/kg/graph")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] /api/kg/graph - 图谱数据获取成功，节点数={len(data['data']['nodes'])}")


def test_settings():
    r = _client.get("/settings")
    data = r.json()
    assert data["success"] is True
    assert data["data"]["provider"] == "dashscope"
    assert data["data"]["model"] == "qwen-plus"
    print(f"[PASS] /api/settings - 设置获取成功，提供商={data['data']['provider']}, 模型={data['data']['model']}")


def test_convs():
    r = _client.get("/convs")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] /api/convs - 对话列表获取成功")


def test_chat():
    r = _client.post("/chat", json={"message": "你好"})
    data = r.json()
    assert data["success"] is True
    assert "conversation_id" in data["data"]
    print(f"[PASS] /api/chat - 聊天接口正常，路径={data['data']['path']}")


def test_kg_search():
    r = _client.get("/kg/search", params={"q": "RAG", "mode": "hybrid", "top_k": 5})
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] /api/kg/search - KG搜索正常")


def test_doc_detail():
    r = _client.get("/docs/1")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] /api/docs/1 - 文档详情获取正常")


def test_delete_node():
    r = _client.delete("/kg/nodes/1")
    print(f"[PASS] /api/kg/nodes/1 DELETE - {r.json().get('message', 'OK')}")


if __name__ == "__main__":
    print("=== 阶段0 验收测试 ===\n")
    test_health()
    test_ingest()
    test_docs_list()
    test_kg_nodes()
    test_kg_create_node()
    test_kg_graph()
    test_settings()
    test_convs()
    test_chat()
    test_kg_search()
    test_doc_detail()
    test_delete_node()
    print("\n=== 全部验收测试通过 ===")
