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

        paper = service.chat_fast_path("记忆压缩论文：DeepSeek 数据分析 Agent 设计。请重点关注技术栈和 Agent 协作方式。")
        paper_id = paper["conversation_id"]
        noise_messages = [
            "无关噪声问题 0：请简单解释一下数据库索引。",
            "切换意图：我想临时问一下 Docker Compose 是什么。",
            "无关噪声问题 1：请简单解释一下 HTTP 状态码。",
            "另一个意图：帮我比较一下 Redis 和 MySQL 的区别。",
        ]
        for msg in noise_messages:
            service.chat_fast_path(msg, paper_id)
        compressed = memory.compress_if_needed(paper_id)
        assert compressed is True
        context = memory.build_memory_context("这篇论文用了什么技术栈？", paper_id)
        prompt_text = context["prompt_text"]
        assert "DeepSeek" in prompt_text or "数据分析" in prompt_text, prompt_text
        assert "Agent" in prompt_text, prompt_text
        assert len(context["recent_turns"]) <= 8
        print("[PASS] long-range compressed recall survives noise and prompt budget")

        noisy_context = memory.build_memory_context("刚才那篇数据分析 Agent 论文重点关注什么？", paper_id)
        noisy_prompt = noisy_context["prompt_text"]
        assert "DeepSeek" in noisy_prompt or "数据分析" in noisy_prompt, noisy_prompt
        assert "技术栈" in noisy_prompt or "Agent" in noisy_prompt, noisy_prompt
        print("[PASS] compressed memory recall under different intent noise")

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
