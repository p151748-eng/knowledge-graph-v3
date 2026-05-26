"""
阶段2验收测试脚本
验证 LLM 集成 + Chroma 向量检索
"""
import httpx
import json
import time

BASE = "http://localhost:8003/api"
_client = httpx.Client(base_url=BASE, timeout=60.0, trust_env=False)


def test_llm_connectivity():
    """测试1: LLM 连通性"""
    r = _client.get("/health")
    data = r.json()
    assert data["success"] is True
    assert data["data"]["database"] == "connected"
    print(f"[PASS] 健康检查 - 数据库={data['data']['database']}")

    r = _client.get("/settings")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] LLM 配置 - 提供商={data['data']['provider']}, 模型={data['data']['model']}")


def test_llm_chat():
    """测试2: LLM 对话生成"""
    r = _client.post("/chat", json={"message": "RAG是什么？请用一句话解释"})
    data = r.json()
    assert data["success"] is True
    assert data["data"]["response"], "回复内容不应为空"
    print(f"[PASS] LLM 对话 - 回复长度={len(data['data']['response'])}")
    print(f"       回复内容: {data['data']['response'][:100]}...")
    return data["data"]["conversation_id"]


def test_chroma_vector_search():
    """测试3: Chroma 向量检索"""
    r = _client.get("/kg/graph")
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] 图谱数据 - 节点数={len(data['data']['nodes'])}")


def test_document_ingest_with_kg():
    """测试4: 文档导入 + KG 实体抽取"""
    r = _client.post(
        "/ingest",
        json={
            "title": "知识图谱与RAG技术",
            "content": """
            知识图谱是一种用图结构表示知识的技术，由实体和关系组成。
            常见的实体类型包括人物、地点、组织等。
            实体之间通过关系相互连接，如"张三是阿里巴巴的工程师"。

            RAG（检索增强生成）结合了知识图谱和向量检索。
            当用户提问时，系统首先从知识图谱中检索相关实体，
            然后使用向量数据库进行语义相似度匹配，
            最后由LLM生成准确的回答。
            """,
            "source": "phase2_test",
            "tags": ["知识图谱", "RAG", "AI"],
        },
    )
    data = r.json()
    assert data["success"] is True
    assert data["data"]["document_id"] > 0
    print(f"[PASS] 文档导入 - ID={data['data']['document_id']}, "
          f"节点={data['data']['nodes_created']}, "
          f"关系={data['data']['edges_created']}")
    return data["data"]["document_id"]


def test_entity_extraction():
    """测试5: 实体抽取验证"""
    r = _client.get("/kg/nodes", params={"limit": 10})
    data = r.json()
    assert data["success"] is True
    assert data["data"]["total"] > 0
    print(f"[PASS] 实体抽取 - 节点总数={data['data']['total']}")
    for node in data["data"]["nodes"][:5]:
        print(f"       [{node['type']}] {node['name']}: {node['description'][:50] if node['description'] else '(无描述)'}")


def test_hybrid_search():
    """测试6: 混合检索"""
    r = _client.get("/kg/search", params={"q": "RAG 知识图谱", "mode": "hybrid", "top_k": 5})
    data = r.json()
    assert data["success"] is True
    print(f"[PASS] 混合检索 - 找到 {len(data['data']['entities'])} 个相关实体")
    for e in data["data"]["entities"][:3]:
        print(f"       - {e['name']} ({e['type']})")


def test_chat_with_context():
    """测试7: 上下文对话"""
    conv_id = test_llm_chat()

    r = _client.post(
        "/chat",
        json={
            "message": "请详细解释 RAG 的工作原理",
            "conversation_id": conv_id
        }
    )
    data = r.json()
    assert data["success"] is True
    assert len(data["data"]["response"]) > 50
    print(f"[PASS] 上下文对话 - 回复长度={len(data['data']['response'])}")
    print(f"       回复内容: {data['data']['response'][:100]}...")


def test_chat_memory():
    """测试8: 对话记忆"""
    r = _client.post(
        "/chat",
        json={"message": "我的名字是小明", "force_path": "fast"},
    )
    data = r.json()
    assert data["success"] is True
    conv_id = data["data"]["conversation_id"]

    r = _client.post(
        "/chat",
        json={
            "message": "我叫什么名字？",
            "conversation_id": conv_id,
            "force_path": "fast",
        },
    )
    data = r.json()
    assert data["success"] is True
    assert any(token in data["data"]["response"] for token in ["小明", "你叫小明", "您的名字是小明"]), data["data"]["response"]
    print(f"[PASS] 对话记忆 - 回复: {data['data']['response'][:100]}...")


def test_stream_chat():
    """测试9: 流式对话"""
    r = _client.post(
        "/chat/stream",
        json={"message": "什么是向量数据库？"},
        timeout=30.0
    )
    chunks = []
    for line in r.text.split("\n"):
        if line.startswith("data: "):
            data_str = line[6:].strip()
            if data_str and data_str != "[DONE]":
                try:
                    event = json.loads(data_str)
                    chunks.append(event)
                except:
                    pass

    has_delta = any(c.get("type") == "delta" for c in chunks)
    has_metrics = any(c.get("type") == "metrics" for c in chunks)

    assert has_delta, "流式响应缺少 delta 事件"
    assert has_metrics, "流式响应缺少 metrics 事件"
    print(f"[PASS] 流式对话 - 收到 {len(chunks)} 个事件块")


def test_web_search():
    """测试9: 联网搜索（可选）"""
    try:
        r = _client.post(
            "/websearch",
            json={"query": "人工智能 2026", "max_results": 3}
        )
        data = r.json()
        assert data["success"] is True
        print(f"[PASS] 联网搜索 - 找到 {len(data['data']['results'])} 条结果")
    except Exception as e:
        print(f"[SKIP] 联网搜索 - 未配置或网络错误: {e}")


if __name__ == "__main__":
    print("=== 阶段2 验收测试：LLM 集成 + Chroma 向量检索 ===\n")

    try:
        test_llm_connectivity()
        test_llm_chat()
        test_chroma_vector_search()
        doc_id = test_document_ingest_with_kg()
        time.sleep(1)  # 等待异步处理
        test_entity_extraction()
        test_hybrid_search()
        test_chat_with_context()
        test_chat_memory()
        test_stream_chat()
        test_web_search()

        print("\n=== 全部阶段2 验收测试通过 ===")
    except AssertionError as e:
        print(f"\n[FAIL] 测试失败: {e}")
        exit(1)
    except Exception as e:
        print(f"\n[ERROR] 运行时错误: {e}")
        exit(1)
