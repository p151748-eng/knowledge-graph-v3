from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, ForeignKey,
    JSON, create_engine, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship, Session, sessionmaker
from sqlalchemy.pool import QueuePool

Base = declarative_base()


class Node(Base):
    """知识图谱节点"""
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    type = Column(String(32), nullable=False, default="entity", index=True)
    description = Column(Text, nullable=True)
    properties = Column("properties", JSON, nullable=True)
    source_docs = Column("source_docs", JSON, nullable=True)
    provenance = Column("provenance", JSON, nullable=True)
    embedding = Column(Text, nullable=True)
    source_doc_ids = Column("source_doc_ids", JSON, nullable=True)
    confidence = Column(Float, default=0.8)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    outgoing_edges: List["Edge"] = relationship(
        "Edge", foreign_keys="Edge.source_id", back_populates="source_node", cascade="all, delete-orphan"
    )
    incoming_edges: List["Edge"] = relationship(
        "Edge", foreign_keys="Edge.target_id", back_populates="target_node", cascade="all, delete-orphan"
    )


class Edge(Base):
    """知识图谱关系"""
    __tablename__ = "edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    relation = Column(String(255), nullable=False)
    type = Column(String(32), nullable=True)
    weight = Column(Float, default=1.0)
    confidence = Column(Float, default=0.8)
    source_docs = Column("source_docs", JSON, nullable=True)
    first_mentioned_in = Column("first_mentioned_in", Integer, nullable=True)
    source_doc_ids = Column("source_doc_ids", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation", name="uk_edge"),
        Index("idx_target", "target_id"),
        Index("idx_relation", "relation"),
    )

    source_node: "Node" = relationship("Node", foreign_keys=[source_id], back_populates="outgoing_edges")
    target_node: "Node" = relationship("Node", foreign_keys=[target_id], back_populates="incoming_edges")


class Document(Base):
    """文档库"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String(512), default="manual")
    tags = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    source_url = Column(String(512), nullable=True)

    __table_args__ = (
        Index("idx_source", "source"),
    )


class DocumentChunk(Base):
    """文档分片"""
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_chunk_doc", "document_id"),
    )


class Conversation(Base):
    """对话"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(512), nullable=True)
    messages = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConversationSummary(Base):
    """会话摘要与活跃焦点"""
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    summary = Column(Text, nullable=True)
    task_state = Column(JSON, nullable=True)
    covered_message_count = Column(Integer, default=0, nullable=False)
    summary_status = Column(String(32), default="idle", nullable=False)
    summary_started_at = Column(DateTime, nullable=True)
    last_summarized_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation: "Conversation" = relationship("Conversation")


class ConversationMemoryItem(Base):
    """会话记忆片段"""
    __tablename__ = "conversation_memory_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False, default="system")
    content = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    keywords = Column(JSON, nullable=True)
    importance = Column(Float, default=0.5)
    message_index = Column(Integer, nullable=True)
    kind = Column(String(32), nullable=False, default="fact", index=True)
    focus_id = Column(String(128), nullable=True, index=True)
    focus_type = Column(String(32), nullable=True, index=True)
    topic_label = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation: "Conversation" = relationship("Conversation")


# ── 数据库引擎与会话工厂 ─────────────────────────────────────────

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        from config import config
        _engine = create_engine(
            config.DATABASE_URL,
            pool_size=5,
            pool_recycle=3600,
            pool_pre_ping=True,
            echo=config.SQL_ECHO,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def get_db():
    """依赖注入获取数据库会话"""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """启动时初始化所有表（仅当表不存在时才创建）"""
    engine = get_engine()
    Base.metadata.create_all(bind=engine, checkfirst=True)
