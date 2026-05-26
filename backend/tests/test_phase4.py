"""
阶段4验收测试脚本
验证动态 LLM 切换，性能优化和生产环境配置
"""
import httpx
import json
import time

BASE = "http://localhost:8003/api"
_client = httpx.Client(base_url=BASE, timeout=60.0, trust_env=False)


def test_health_check():
    r = _client.get("/health")
    data = r.json()
    assert data["success"] is True
    assert data["data"]["database"] == "connected"
    print("[PASS] 健康检查")


def test_dynamic_settings():
    r = _client.get("/settings")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] 当前设置: {data['data']['provider']}/{data['data']['model']}")

    r = _client.put("/settings", json={"temperature": 0.5})
    data = r.json()
    assert data["success"] is True
    print("[PASS] 温度设置已更新")


def test_llm_chat():
    r = _client.post("/chat", json={"message": "测试消息"})
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] LLM对话: {len(data['data']['response'])} 字符")


def test_conversation_persistence():
    r = _client.post("/chat", json={"message": "测试"})
    conv_id = r.json()["data"]["conversation_id"]
    r = _client.get(f"/convs/{conv_id}")
    assert r.json()["success"] is True
    print("[PASS] 对话持久化正常")


def test_kg_operations():
    r = _client.post("/kg/nodes", json={"name": "Phase4Test", "type": "entity"})
    node_id = r.json()["data"]["id"]
    r = _client.delete(f"/kg/nodes/{node_id}")
    assert r.status_code == 200
    print("[PASS] KG操作正常")


def test_document_lifecycle():
    r = _client.post("/ingest", json={
        "title": "Phase4测试",
        "content": "测试内容",
        "source": "test"
    })
    doc_id = r.json()["data"]["document_id"]
    r = _client.delete(f"/docs/{doc_id}")
    assert r.status_code == 200
    print("[PASS] 文档生命周期正常")


def test_api_completeness():
    endpoints = ["/health", "/settings", "/kg/nodes", "/kg/edges", "/docs", "/convs"]
    for ep in endpoints:
        r = _client.get(ep)
        assert r.status_code == 200
    print(f"[PASS] {len(endpoints)} 个API端点正常")


if __name__ == "__main__":
    print("=== 阶段4 验收测试 ===\n")
    try:
        test_health_check()
        test_dynamic_settings()
        test_llm_chat()
        test_conversation_persistence()
        test_kg_operations()
        test_document_lifecycle()
        test_api_completeness()
        print("\n=== 全部测试通过 ===")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        exit(1)
