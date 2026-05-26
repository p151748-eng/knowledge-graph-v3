"""
阶段3验收测试脚本
验证前端增强功能：对话历史侧边栏、图谱搜索、路径选择等
"""
import httpx
import json

BASE = "http://localhost:8003/api"
_client = httpx.Client(base_url=BASE, timeout=30.0, trust_env=False)


def test_conversations_api():
    """测试1: 对话历史 API"""
    r = _client.get("/convs")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] 对话历史 API - 共 {len(data['data']['conversations'])} 条对话")


def test_chat_with_conversation():
    """测试2: 对话保存"""
    r = _client.post("/chat", json={"message": "阶段3测试问题"})
    data = r.json()
    assert data["success"] is True
    conv_id = data["data"]["conversation_id"]
    print(f"[PASS] 对话保存 - 对话ID={conv_id}")

    # 验证对话历史包含新对话
    r = _client.get("/convs")
    data = r.json()
    conv_ids = [c["id"] for c in data["data"]["conversations"]]
    assert conv_id in conv_ids, "新对话未出现在历史中"
    print(f"[PASS] 对话历史验证 - 新对话已保存")

    return conv_id


def test_conversation_detail():
    """测试3: 对话详情"""
    r = _client.post("/chat", json={"message": "详细测试"})
    data = r.json()
    assert data["success"] is True
    conv_id = data["data"]["conversation_id"]

    r = _client.get(f"/convs/{conv_id}")
    data = r.json()
    assert data["success"] is True
    assert data["data"]["id"] == conv_id
    assert len(data["data"]["messages"]) >= 2  # user + assistant
    print(f"[PASS] 对话详情 - 包含 {len(data['data']['messages'])} 条消息")


def test_kg_search():
    """测试4: KG 节点搜索"""
    r = _client.get("/kg/search", params={"q": "RAG", "mode": "hybrid", "top_k": 10})
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] KG 搜索 - 找到 {len(data['data']['entities'])} 个相关实体")


def test_kg_graph():
    """测试5: 图谱数据"""
    r = _client.get("/kg/graph")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] 图谱数据 - 节点={len(data['data']['nodes'])}, 关系={len(data['data']['links'])}")


def test_kg_nodes_crud():
    """测试6: 节点 CRUD"""
    # 创建
    r = _client.post("/kg/nodes", json={"name": "测试节点Phase3", "type": "entity"})
    data = r.json()
    assert data["success"] is True
    node_id = data["data"]["id"]
    print(f"[PASS] 节点创建 - ID={node_id}")

    # 更新
    r = _client.put(f"/kg/nodes/{node_id}", json={"name": "测试节点Phase3更新"})
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] 节点更新 - 已更新")

    # 删除
    r = _client.delete(f"/kg/nodes/{node_id}")
    assert r.status_code == 200
    print(f"[PASS] 节点删除 - 已删除")


def test_document_lifecycle():
    """测试7: 文档完整生命周期"""
    # 导入
    r = _client.post("/ingest", json={
        "title": "阶段3测试文档",
        "content": "这是用于测试的文档内容，包含一些关键词用于检索测试。",
        "source": "phase3_test",
    })
    data = r.json()
    assert data["success"] is True
    doc_id = data["data"]["document_id"]
    print(f"[PASS] 文档导入 - ID={doc_id}")

    # 列表
    r = _client.get("/docs", params={"search": "阶段3"})
    data = r.json()
    assert data["success"] is True
    found = any(d["id"] == doc_id for d in data["data"]["documents"])
    assert found, "新文档未出现在列表中"
    print(f"[PASS] 文档列表 - 新文档已保存")

    # 详情
    r = _client.get(f"/docs/{doc_id}")
    data = r.json()
    assert data["success"] is True
    assert data["data"]["title"] == "阶段3测试文档"
    print(f"[PASS] 文档详情 - 标题正确")

    # 删除
    r = _client.delete(f"/docs/{doc_id}")
    assert r.status_code == 200
    print(f"[PASS] 文档删除 - 已删除")


def test_settings_api():
    """测试8: 设置 API"""
    r = _client.get("/settings")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] 设置获取 - 提供商={data['data']['provider']}, 模型={data['data']['model']}")

    r = _client.put("/settings", json={"model": "qwen-max"})
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] 设置更新 - 已更新")


def test_health_check():
    """测试9: 健康检查"""
    r = _client.get("/health")
    data = r.json()
    assert data["success"] is True
    assert data["data"]["database"] == "connected"
    print(f"[PASS] 健康检查 - 所有服务正常")


def test_conversation_delete():
    """测试10: 对话删除"""
    # 创建对话
    r = _client.post("/chat", json={"message": "测试删除"})
    data = r.json()
    assert data["success"] is True
    conv_id = data["data"]["conversation_id"]

    # 删除对话
    r = _client.delete(f"/convs/{conv_id}")
    assert r.status_code == 200
    print(f"[PASS] 对话删除 - ID={conv_id} 已删除")


if __name__ == "__main__":
    print("=== 阶段3 验收测试：前端增强功能 ===\n")

    try:
        test_conversations_api()
        test_chat_with_conversation()
        test_conversation_detail()
        test_kg_search()
        test_kg_graph()
        test_kg_nodes_crud()
        test_document_lifecycle()
        test_settings_api()
        test_health_check()
        test_conversation_delete()

        print("\n=== 全部阶段3 验收测试通过 ===")
    except AssertionError as e:
        print(f"\n[FAIL] 测试失败: {e}")
        exit(1)
    except Exception as e:
        print(f"\n[ERROR] 运行时错误: {e}")
        exit(1)
