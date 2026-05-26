"""
Run backend regression checks for hybrid conversation memory.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import ConversationMemoryItem, ConversationSummary, get_session_factory, init_db
from services.chat import ChatService
from services.memory import MemoryService
from services.retrieval import RetrievalService


def assert_contains(text, tokens):
    assert any(token in text for token in tokens), text


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    init_db()
    db = get_session_factory()()
    try:
        service = ChatService(db)

        first = service.chat_fast_path("我的名字是小明")
        conv_id = first["conversation_id"]
        second = service.chat_fast_path("我叫什么名字？", conv_id)
        assert conv_id == second["conversation_id"]
        assert_contains(second["response"], ["小明", "你叫小明", "您的名字是小明"])
        print("[PASS] short-term memory")

        memory = MemoryService(db)
        conv = db.query(ConversationSummary).filter(ConversationSummary.conversation_id == conv_id).first()
        assert conv is not None
        print("[PASS] summary row created")

        paper = service.chat_fast_path("接下来分析论文：《基于DeepSeek的汽车数据分析Agent设计》，重点关注技术栈和Agent构建方式。")
        paper_id = paper["conversation_id"]
        for i in range(4):
            service.chat_fast_path(f"无关测试问题 {i}：请简单解释一个数据库概念。", paper_id)
        memory.compress_if_needed(paper_id)
        context = memory.build_memory_context("这篇论文用了什么技术栈？", paper_id)
        prompt_text = context["prompt_text"]
        assert "DeepSeek" in prompt_text or "汽车数据分析" in prompt_text, prompt_text
        assert len(context["recent_turns"]) <= 4
        print("[PASS] long-range compressed recall and prompt budget")

        state = context["task_state"]
        old_focus = (state.get("active_focus") or {}).get("focus_id")
        state = memory.update_active_focus("换一篇：《多模态知识图谱增强RAG系统》", state)
        new_focus = (state.get("active_focus") or {}).get("focus_id")
        assert new_focus and new_focus != old_focus
        assert "多模态知识图谱" in new_focus
        print("[PASS] active focus auto-switch")

        other = service.chat_fast_path("我的项目代号是银河A，不要和其他会话混淆。")
        other_id = other["conversation_id"]
        memory.compress_if_needed(other_id)
        isolated = memory.build_memory_context("我的项目代号是什么？", other_id)["prompt_text"]
        cross = memory.build_memory_context("我的项目代号是什么？", paper_id)["prompt_text"]
        assert "银河A" in isolated
        assert "银河A" not in cross
        print("[PASS] conversation isolation")

        assert RetrievalService(db).delete_conversation(other_id) is True
        deleted_summary = db.query(ConversationSummary).filter(ConversationSummary.conversation_id == other_id).first()
        deleted_items = db.query(ConversationMemoryItem).filter(ConversationMemoryItem.conversation_id == other_id).count()
        assert deleted_summary is None
        assert deleted_items == 0
        print("[PASS] cleanup on delete")

        print("hybrid memory regression passed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
