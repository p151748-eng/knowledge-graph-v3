"""
MemoryService: conversation memory compression, focus tracking, and recall.
"""

import json
import re
from datetime import datetime, timedelta
from threading import Thread
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from chroma.manager import chroma_manager
from llm.manager import llm_manager
from models.db import Conversation, ConversationMemoryItem, ConversationSummary, get_session_factory, init_db

RECENT_HISTORY_ROUNDS = 4
# 对于大纲生成等需要完整上下文的任务，需要保留更多历史轮次
SUMMARY_TRIGGER_MESSAGES = 8
SUMMARY_TRIGGER_DELTA = 4
SUMMARY_LOCK_TIMEOUT_SECONDS = 300
MEMORY_COLLECTION = "conversation_memory"
_MEMORY_TABLES_READY = False

SWITCH_PATTERNS = ["换一篇", "换一个", "另一篇", "另一个", "这次看", "现在看", "别说刚才", "不要刚才"]
BACK_PATTERNS = ["回到", "刚才那篇", "上一个", "前一个", "之前那个", "继续刚才"]
COMPARE_PATTERNS = ["比较", "对比", "区别", "异同"]
PAPER_PATTERNS = [r"《([^》]{2,80})》", r"论文[：: ]+([^，。\n]{2,80})", r"题目[：: ]+([^，。\n]{2,80})"]
DOC_PATTERNS = [r"文档[：: ]+([^，。\n]{2,80})", r"文件[：: ]+([^，。\n]{2,80})"]


class MemoryService:
    """Builds bounded memory context and keeps compressed memory up to date."""

    def __init__(self, db: Session, llm=None):
        self.db = db
        self.llm = llm if llm is not None else llm_manager
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        global _MEMORY_TABLES_READY
        if _MEMORY_TABLES_READY:
            return
        try:
            bind = self.db.get_bind()
            ConversationSummary.__table__.create(bind=bind, checkfirst=True)
            ConversationMemoryItem.__table__.create(bind=bind, checkfirst=True)
            _MEMORY_TABLES_READY = True
        except Exception:
            try:
                init_db()
                _MEMORY_TABLES_READY = True
            except Exception:
                pass

    def build_memory_context(self, query: str, conversation_id: Optional[int]) -> Dict[str, Any]:
        if not conversation_id:
            return {"summary": "", "task_state": {}, "snippets": [], "recent_turns": [], "prompt_text": ""}

        summary = self._get_or_create_summary(conversation_id)
        task_state = summary.task_state or {}
        task_state = self.update_active_focus(query, task_state)
        if task_state != (summary.task_state or {}):
            summary.task_state = task_state
            flag_modified(summary, "task_state")
            self.db.commit()

        snippets = self.recall(query, conversation_id, task_state=task_state, top_k=5)
        recent_turns = self.load_recent_turns(conversation_id, rounds=RECENT_HISTORY_ROUNDS)
        prompt_text = self._format_prompt_text(summary.summary or "", task_state, snippets, recent_turns)
        return {
            "summary": summary.summary or "",
            "task_state": task_state,
            "snippets": snippets,
            "recent_turns": recent_turns,
            "prompt_text": prompt_text,
        }

    def load_recent_turns(self, conversation_id: Optional[int], rounds: int = RECENT_HISTORY_ROUNDS) -> List[dict]:
        if not conversation_id:
            return []
        conv = self.db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conv or not conv.messages:
            return []
        history = conv.messages[-(rounds * 2):]
        return [
            {
                "role": m.get("role", "user"),
                "content": m.get("content", ""),
                "path": m.get("path"),
                "intent": m.get("intent"),
                "route_decision": m.get("route_decision"),
            }
            for m in history
        ]

    def update_after_turn(self, conversation_id: int, async_update: bool = True) -> None:
        if async_update:
            Thread(target=self._background_update, args=(conversation_id,), daemon=True).start()
            return
        self.compress_if_needed(conversation_id)

    def _background_update(self, conversation_id: int) -> None:
        db = get_session_factory()()
        try:
            MemoryService(db, self.llm).compress_if_needed(conversation_id)
        finally:
            db.close()

    def compress_if_needed(self, conversation_id: int) -> bool:
        if not self._acquire_summary_lock(conversation_id):
            return False

        summary = self._get_or_create_summary(conversation_id)
        try:
            conv = self.db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv or not conv.messages:
                self._release_summary_lock(summary)
                return False

            start = int(summary.covered_message_count or 0)
            end = len(conv.messages)
            if end <= start:
                self._release_summary_lock(summary)
                return False
            if end < SUMMARY_TRIGGER_MESSAGES and end - start < SUMMARY_TRIGGER_DELTA:
                self._release_summary_lock(summary)
                return False

            new_messages = conv.messages[start:end]
            task_state = summary.task_state or {}
            result = self._compress_with_llm(summary.summary or "", task_state, new_messages)
            merged_summary = result.get("summary") or result.get("summary_delta") or self._fallback_summary(new_messages)
            merged_task_state = result.get("task_state") or task_state
            merged_task_state = self._normalize_task_state(merged_task_state)

            memory_items = result.get("memory_items") or []
            if not memory_items:
                memory_items = self._fallback_memory_items(new_messages, merged_task_state)
            self._store_memory_items(conversation_id, memory_items, start, merged_task_state)

            summary.summary = merged_summary[:6000]
            summary.task_state = merged_task_state
            summary.covered_message_count = end
            summary.summary_status = "idle"
            summary.summary_started_at = None
            summary.last_summarized_at = datetime.utcnow()
            summary.last_error = None
            flag_modified(summary, "task_state")
            self.db.commit()
            return True
        except Exception as exc:
            self.db.rollback()
            failed_summary = self._get_or_create_summary(conversation_id)
            failed_summary.summary_status = "failed"
            failed_summary.summary_started_at = None
            failed_summary.last_error = str(exc)[:1000]
            self.db.commit()
            return False

    def recall(self, query: str, conversation_id: int, task_state: Optional[Dict[str, Any]] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        task_state = task_state or self._get_or_create_summary(conversation_id).task_state or {}
        active_focus = task_state.get("active_focus") or {}
        active_focus_id = active_focus.get("focus_id")
        sql_hits = self._recall_sql(query, conversation_id, active_focus_id, top_k=top_k)
        vector_hits = self._recall_vector(query, conversation_id, active_focus_id, top_k=top_k)
        merged: Dict[int, Dict[str, Any]] = {}
        for hit in sql_hits + vector_hits:
            memory_id = hit.get("id") or hit.get("memory_item_id")
            if not memory_id:
                continue
            score = hit.get("rank_score", 0.0)
            if memory_id not in merged or score > merged[memory_id].get("rank_score", 0.0):
                merged[memory_id] = hit
        return sorted(merged.values(), key=lambda item: item.get("rank_score", 0.0), reverse=True)[:top_k]

    def update_active_focus(self, message: str, task_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        state = self._normalize_task_state(task_state or {})
        action, focus = self._classify_focus_rule(message, state)
        if action == "continue":
            active = state.get("active_focus") or {}
            if active:
                active["intent"] = self._shorten(message, 160)
                active["updated_at"] = datetime.utcnow().isoformat()
                state["active_focus"] = active
                self._upsert_focus_stack(state, active)
            return state
        if action in {"switch", "back", "compare"} and focus:
            state["active_focus"] = focus
            self._upsert_focus_stack(state, focus)
        return state

    def cleanup_conversation(self, conversation_id: int) -> None:
        items = self.db.query(ConversationMemoryItem).filter(ConversationMemoryItem.conversation_id == conversation_id).all()
        for item in items:
            chroma_manager.delete_from(MEMORY_COLLECTION, f"memory:{item.id}")
        self.db.query(ConversationMemoryItem).filter(ConversationMemoryItem.conversation_id == conversation_id).delete()
        self.db.query(ConversationSummary).filter(ConversationSummary.conversation_id == conversation_id).delete()

    def _get_or_create_summary(self, conversation_id: int) -> ConversationSummary:
        summary = self.db.query(ConversationSummary).filter(ConversationSummary.conversation_id == conversation_id).first()
        if summary:
            return summary
        summary = ConversationSummary(
            conversation_id=conversation_id,
            summary="",
            task_state={"active_focus": {}, "focus_stack": []},
            covered_message_count=0,
            summary_status="idle",
        )
        self.db.add(summary)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            summary = self.db.query(ConversationSummary).filter(ConversationSummary.conversation_id == conversation_id).first()
            if summary:
                return summary
            raise
        self.db.refresh(summary)
        return summary

    def _acquire_summary_lock(self, conversation_id: int) -> bool:
        summary = self._get_or_create_summary(conversation_id)
        now = datetime.utcnow()
        stale_before = now - timedelta(seconds=SUMMARY_LOCK_TIMEOUT_SECONDS)
        if summary.summary_status == "running" and summary.summary_started_at and summary.summary_started_at > stale_before:
            return False
        summary.summary_status = "running"
        summary.summary_started_at = now
        self.db.commit()
        return True

    def _release_summary_lock(self, summary: ConversationSummary) -> None:
        summary.summary_status = "idle"
        summary.summary_started_at = None
        self.db.commit()

    def _compress_with_llm(self, old_summary: str, task_state: Dict[str, Any], messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        text = "\n".join([f"{m.get('role')}: {m.get('content', '')[:1000]}" for m in messages])
        prompt = f"""请把以下新增对话压缩成可长期记忆的 JSON，不要输出 JSON 以外的内容。

旧摘要：
{old_summary or '（无）'}

当前任务状态：
{json.dumps(task_state, ensure_ascii=False)}

新增对话：
{text}

返回格式：
{{
  "summary": "融合旧摘要后的完整摘要，限 1200 字",
  "task_state": {{"active_focus": {{}}, "focus_stack": []}},
  "memory_items": [
    {{"kind": "fact|preference|task|paper_context|qa", "summary": "短记忆", "content": "原始依据", "keywords": ["关键词"], "importance": 0.8, "focus_id": "", "focus_type": "", "topic_label": ""}}
  ]
}}
"""
        response = self.llm.complete(prompt, system_prompt="你是对话记忆压缩器，只返回合法 JSON。", temperature=0.1).content
        return self._parse_json(response)

    def _store_memory_items(self, conversation_id: int, items: List[Dict[str, Any]], base_index: int, task_state: Dict[str, Any]) -> None:
        active = task_state.get("active_focus") or {}
        for offset, item in enumerate(items[:8]):
            summary_text = self._shorten(item.get("summary") or item.get("content") or "", 700)
            content = self._shorten(item.get("content") or summary_text, 1200)
            if not summary_text and not content:
                continue
            memory = ConversationMemoryItem(
                conversation_id=conversation_id,
                role=item.get("role", "system"),
                content=content or summary_text,
                summary=summary_text or content,
                keywords=item.get("keywords") or [],
                importance=float(item.get("importance", 0.5) or 0.5),
                message_index=base_index + offset,
                kind=item.get("kind") or "fact",
                focus_id=item.get("focus_id") or active.get("focus_id"),
                focus_type=item.get("focus_type") or active.get("focus_type"),
                topic_label=item.get("topic_label") or active.get("title"),
            )
            self.db.add(memory)
            self.db.flush()
            self._upsert_memory_vector(memory)
        self.db.commit()

    def _upsert_memory_vector(self, memory: ConversationMemoryItem) -> None:
        try:
            text = memory.summary or memory.content
            embedding = self.llm.embed([text])[0]
            chroma_manager.upsert_to(
                MEMORY_COLLECTION,
                doc_id=f"memory:{memory.id}",
                text=text,
                metadata={
                    "kind": "conversation_memory",
                    "conversation_id": memory.conversation_id,
                    "memory_item_id": memory.id,
                    "memory_kind": memory.kind,
                    "importance": float(memory.importance or 0.5),
                    "focus_id": memory.focus_id or "",
                    "focus_type": memory.focus_type or "",
                    "topic_label": memory.topic_label or "",
                },
                embedding=embedding,
            )
        except Exception:
            pass

    def _recall_sql(self, query: str, conversation_id: int, focus_id: Optional[str], top_k: int) -> List[Dict[str, Any]]:
        terms = [term for term in re.split(r"\s+|，|。|,|\?|？", query) if len(term) >= 2][:8]
        q = self.db.query(ConversationMemoryItem).filter(ConversationMemoryItem.conversation_id == conversation_id)
        if focus_id:
            focused = q.filter(ConversationMemoryItem.focus_id == focus_id).order_by(ConversationMemoryItem.importance.desc(), ConversationMemoryItem.created_at.desc()).limit(top_k).all()
        else:
            focused = []
        conditions = []
        for term in terms:
            like = f"%{term}%"
            conditions.extend([ConversationMemoryItem.summary.like(like), ConversationMemoryItem.content.like(like), ConversationMemoryItem.topic_label.like(like)])
        keyword_hits = q.filter(or_(*conditions)).order_by(ConversationMemoryItem.importance.desc(), ConversationMemoryItem.created_at.desc()).limit(top_k).all() if conditions else []
        results = []
        for item in list(focused) + list(keyword_hits):
            results.append(self._memory_item_to_hit(item, 1.0 + float(item.importance or 0.0)))
        return results

    def _recall_vector(self, query: str, conversation_id: int, focus_id: Optional[str], top_k: int) -> List[Dict[str, Any]]:
        try:
            embedding = self.llm.embed([query])[0]
            where = {"conversation_id": conversation_id}
            if focus_id:
                where = {"$and": [{"conversation_id": conversation_id}, {"focus_id": focus_id}]}
            hits = chroma_manager.query_collection(MEMORY_COLLECTION, embedding, top_k=top_k, where=where)
            if not hits and focus_id:
                hits = chroma_manager.query_collection(MEMORY_COLLECTION, embedding, top_k=top_k, where={"conversation_id": conversation_id})
            results = []
            for hit in hits:
                metadata = hit.get("metadata") or {}
                item = self.db.query(ConversationMemoryItem).filter(ConversationMemoryItem.id == metadata.get("memory_item_id")).first()
                if item:
                    score = 1.0 / (1.0 + float(hit.get("score", 0.0))) + float(item.importance or 0.0)
                    results.append(self._memory_item_to_hit(item, score))
            return results
        except Exception:
            return []

    def _memory_item_to_hit(self, item: ConversationMemoryItem, rank_score: float) -> Dict[str, Any]:
        return {
            "id": item.id,
            "memory_item_id": item.id,
            "summary": item.summary or item.content,
            "content": item.content,
            "kind": item.kind,
            "importance": float(item.importance or 0.0),
            "focus_id": item.focus_id,
            "focus_type": item.focus_type,
            "topic_label": item.topic_label,
            "rank_score": rank_score,
        }

    def _format_prompt_text(self, summary: str, task_state: Dict[str, Any], snippets: List[Dict[str, Any]], recent_turns: Optional[List[dict]] = None) -> str:
        parts = []
        active = (task_state or {}).get("active_focus") or {}
        if active:
            parts.append(f"【当前焦点】{active.get('title') or active.get('focus_id')}；意图：{active.get('intent', '')}")
        if summary:
            parts.append(f"【会话摘要】{summary[:1200]}")
        if snippets:
            lines = [f"- {s.get('summary') or s.get('content')}" for s in snippets[:5]]
            parts.append("【相关历史片段】\n" + "\n".join(lines))
        if recent_turns:
            # 检测是否为大纲/开题任务，需要更完整的上下文
            is_outline_task = any(
                kw in (msg.get('content', '') or '')
                for msg in recent_turns
                for kw in ['选题', '开题', '大纲', '提纲', 'outline', '基于']
            )
            truncate_limit = 480 if is_outline_task else 240
            recent_lines = []
            for msg in recent_turns[-6:]:
                role = "用户" if msg.get("role") == "user" else "助手"
                recent_lines.append(f"{role}: {self._shorten(msg.get('content', ''), truncate_limit)}")
            if recent_lines:
                parts.append("【最近原文】\n" + "\n".join(recent_lines))
        if not parts and recent_turns:
            recent_lines = []
            for msg in recent_turns[-4:]:
                role = "用户" if msg.get("role") == "user" else "助手"
                recent_lines.append(f"{role}: {self._shorten(msg.get('content', ''), 240)}")
            return "\n\n【对话记忆】\n【最近原文】\n" + "\n".join(recent_lines)
        if not parts:
            return ""
        return "\n\n【对话记忆】\n" + "\n".join(parts)

    def _classify_focus_rule(self, message: str, state: Dict[str, Any]) -> tuple[str, Optional[Dict[str, Any]]]:
        text = message or ""
        if any(p in text for p in COMPARE_PATTERNS):
            return "compare", self._make_focus("comparison", self._shorten(text, 80), text, confidence=0.75)
        if any(p in text for p in BACK_PATTERNS):
            stack = state.get("focus_stack") or []
            inactive = [item for item in stack if item.get("status") != "active"]
            if inactive:
                focus = dict(inactive[-1])
                focus["status"] = "active"
                focus["updated_at"] = datetime.utcnow().isoformat()
                return "back", focus
        extracted = self._extract_focus(text)
        if extracted and (any(p in text for p in SWITCH_PATTERNS) or not (state.get("active_focus") or {}).get("focus_id")):
            return "switch", extracted
        if any(p in text for p in SWITCH_PATTERNS):
            return "switch", self._make_focus("topic", self._shorten(text, 80), text, confidence=0.72)
        return "continue", None

    def _extract_focus(self, text: str) -> Optional[Dict[str, Any]]:
        for pattern in PAPER_PATTERNS:
            match = re.search(pattern, text)
            if match:
                title = match.group(1).strip()
                return self._make_focus("paper", title, text, confidence=0.9)
        for pattern in DOC_PATTERNS:
            match = re.search(pattern, text)
            if match:
                title = match.group(1).strip()
                return self._make_focus("document", title, text, confidence=0.86)
        return None

    def _make_focus(self, focus_type: str, title: str, intent: str, confidence: float) -> Dict[str, Any]:
        safe_title = self._shorten(title.strip() or focus_type, 80)
        return {
            "focus_id": f"{focus_type}:{safe_title}",
            "focus_type": focus_type,
            "title": safe_title,
            "intent": self._shorten(intent, 160),
            "confidence": confidence,
            "status": "active",
            "updated_at": datetime.utcnow().isoformat(),
        }

    def _upsert_focus_stack(self, state: Dict[str, Any], active: Dict[str, Any]) -> None:
        stack = state.get("focus_stack") or []
        next_stack = []
        for item in stack:
            item = dict(item)
            item["status"] = "active" if item.get("focus_id") == active.get("focus_id") else "inactive"
            if item.get("focus_id") != active.get("focus_id"):
                next_stack.append(item)
        active_item = dict(active)
        active_item["status"] = "active"
        next_stack.append(active_item)
        state["focus_stack"] = next_stack[-8:]

    def _normalize_task_state(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                value = {"summary": value}
        if not isinstance(value, dict):
            value = {}
        value.setdefault("active_focus", {})
        value.setdefault("focus_stack", [])
        return value

    def _parse_json(self, content: str) -> Dict[str, Any]:
        text = (content or "").strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        return json.loads(text)

    def _fallback_summary(self, messages: List[Dict[str, Any]]) -> str:
        lines = []
        for msg in messages[-8:]:
            role = "用户" if msg.get("role") == "user" else "助手"
            lines.append(f"{role}: {self._shorten(msg.get('content', ''), 180)}")
        return "\n".join(lines)

    def _fallback_memory_items(self, messages: List[Dict[str, Any]], task_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        active = task_state.get("active_focus") or {}
        items = []
        for msg in messages:
            content = msg.get("content", "")
            if msg.get("role") == "user" and len(content.strip()) >= 4:
                items.append({
                    "kind": active.get("focus_type") or "fact",
                    "summary": self._shorten(content, 220),
                    "content": content,
                    "keywords": self._keywords(content),
                    "importance": 0.7 if active else 0.5,
                    "focus_id": active.get("focus_id"),
                    "focus_type": active.get("focus_type"),
                    "topic_label": active.get("title"),
                })
        return items[:6]

    def _keywords(self, text: str) -> List[str]:
        words = re.findall(r"[一-龥A-Za-z0-9]{2,}", text or "")
        return list(dict.fromkeys(words[:12]))

    def _shorten(self, text: str, limit: int) -> str:
        text = (text or "").strip()
        return text if len(text) <= limit else text[:limit]
