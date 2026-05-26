"""
RetrievalService: 检索服务。
封装对话历史管理和 KG 检索。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from models.db import Conversation
from services.memory import MemoryService


class RetrievalService:
    """对话历史管理服务"""

    def __init__(self, db: Session):
        self.db = db

    def list_conversations(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Conversation], int]:
        """获取对话列表"""
        query = self.db.query(Conversation)
        total = query.count()
        convs = query.order_by(Conversation.updated_at.desc()).offset(offset).limit(limit).all()
        return convs, total

    def get_conversation(self, conv_id: int) -> Optional[Conversation]:
        """获取对话详情"""
        return self.db.query(Conversation).filter(Conversation.id == conv_id).first()

    def delete_conversation(self, conv_id: int) -> bool:
        """删除对话"""
        conv = self.db.query(Conversation).filter(Conversation.id == conv_id).first()
        if not conv:
            return False
        try:
            MemoryService(self.db).cleanup_conversation(conv_id)
        except Exception:
            pass
        self.db.delete(conv)
        self.db.commit()
        return True

    def format_conversation(self, conv: Conversation) -> Dict[str, Any]:
        """格式化对话数据"""
        messages = conv.messages or []
        return {
            "id": conv.id,
            "title": conv.title or f"对话 {conv.id}",
            "message_count": len(messages) // 2,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
        }

    def format_messages(self, conv: Conversation) -> List[Dict[str, Any]]:
        """格式化消息列表"""
        messages = conv.messages or []
        result = []
        for msg in messages:
            result.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("timestamp"),
                "sources": msg.get("sources", []),
            })
        return result
