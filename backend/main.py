"""
KG-Agent System v2 - FastAPI 主入口
"""

import logging
import time
import json
import io
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from config import config
from models.db import Document, DocumentChunk, Edge, Node, get_db, init_db
from models.api import (
    ChatRequest, ChatResponse, ChatData,
    WebSearchRequest, WebSearchResponse, WebSearchData, SearchResultItem,
    IngestRequest, IngestResponse, IngestResultData, ArxivIngestRequest,
    DocsListResponse, DocsListData, DocumentItem,
    DocDetailResponse, DocDetailData,
    NodeCreateRequest, NodeUpdateRequest,
    NodesListResponse, NodesListData, NodeItem,
    NodeCreateResponse, NodeCreateData,
    EdgesListResponse, EdgesListData, EdgeItem,
    EdgeCreateRequest,
    KGSearchRequest, KGSearchResponse, KGSearchData,
    KGSearchEntityItem, KGSearchRelationItem,
    GraphData,
    ConvsListResponse, ConvsListData, ConvItem,
    ConvDetailResponse, ConvDetailData,
    SettingsData, SettingsResponse, SettingsUpdateRequest,
    HealthResponse, HealthData,
    ErrorResponse, ErrorDetail,
)
from services.chat import ChatService
from services.kg import KGService
from services.graph_retrieval import GraphRetrievalService
from services.ingest import IngestService
from services.arxiv_importer import ArxivImporter
from services.retrieval import RetrievalService

# ── 日志配置 ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ── 启动事件 ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("KG-Agent System v2 启动中...")
    try:
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
    yield
    logger.info("KG-Agent System v2 关闭")


# ── FastAPI 应用 ──────────────────────────────────────────────────

app = FastAPI(
    title="KG-Agent System API",
    version="2.0.0",
    description="基于 RAG + 知识图谱的智能个人知识库系统",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 辅助函数 ──────────────────────────────────────────────────────

def extract_chunk_metadata(content: str):
    labels = {
        "chunk_type": "类型",
        "section_path": "章节",
        "paper_title": "论文",
        "authors": "作者",
        "year": "年份",
        "method_name": "方法",
        "metric": "指标",
        "dataset": "数据集",
    }
    metadata = {}
    for key, label in labels.items():
        marker = f"【{label}】"
        for line in (content or "").splitlines():
            if line.startswith(marker):
                value = line[len(marker):].strip()
                if value:
                    metadata[key] = value
                break
    return metadata


def success_response(data, message="操作成功"):
    return {"success": True, "data": data, "message": message}


def error_response(code: str, message: str, details=None):
    return {"success": False, "error": {"code": code, "message": message, "details": details}}


# ── API 路由 ──────────────────────────────────────────────────────

# 健康检查
@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health_check(db: Session = Depends(get_db)):
    db_status = "connected"
    llm_status = "available"
    web_status = "available"

    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"

    return {
        "success": True,
        "data": {
            "status": "healthy" if db_status == "connected" else "degraded",
            "database": db_status,
            "llm": llm_status,
            "web_search": web_status,
            "version": "2.0.0",
        }
    }


# ── 对话 API ──────────────────────────────────────────────────────

@app.post("/api/chat", tags=["chat"])
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        service = ChatService(db)
        result = service.chat(req.message, req.conversation_id, req.force_path)

        return success_response(ChatData(**result))
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/fast", tags=["chat"])
def chat_fast(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        service = ChatService(db)
        result = service.chat(req.message, req.conversation_id, "fast")
        return success_response(ChatData(**result))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/pipeline", tags=["chat"])
def chat_pipeline(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        service = ChatService(db)
        result = service.chat(req.message, req.conversation_id, "pipeline")
        return success_response(ChatData(**result))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/paper", tags=["chat"])
def chat_paper(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        service = ChatService(db)
        result = service.chat(req.message, req.conversation_id, "paper_assistant")
        return success_response(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/self-rag", tags=["chat"])
def chat_self_rag(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        service = ChatService(db)
        result = service.chat(req.message, req.conversation_id, "self_rag")
        return success_response(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream", tags=["chat"])
async def chat_stream(req: ChatRequest, db: Session = Depends(get_db)):
    """SSE 流式对话"""
    service = ChatService(db)

    # 前端 chat_path: auto -> 后端自动判断；fast/pipeline/paper/self_rag/crag -> 强制对应路径
    force_path = None
    if req.chat_path == 'fast':
        force_path = 'fast'
    elif req.chat_path == 'pipeline':
        force_path = 'pipeline'
    elif req.chat_path in {'paper', 'paper_assistant', 'self_rag', 'crag'}:
        force_path = req.chat_path
    # auto: force_path=None，后端自动复杂度路由

    async def event_generator():
        try:
            async for event in service.stream_chat(req.message, req.conversation_id, force_path):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ── 联网搜索 API ──────────────────────────────────────────────────

@app.post("/api/websearch", response_model=WebSearchResponse, tags=["search"])
def web_search(req: WebSearchRequest, db: Session = Depends(get_db)):
    try:
        from tools.web_search import WebSearchTool
        tool = WebSearchTool(db)
        result = tool.execute(
            req.query,
            max_results=req.max_results,
            save=req.save_to_kg or req.save_to_docs,
        )
        return success_response(WebSearchData(**result))
    except Exception as e:
        logger.error(f"WebSearch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 文档 API ──────────────────────────────────────────────────────

@app.post("/api/ingest", response_model=IngestResponse, tags=["docs"])
def ingest_text(req: IngestRequest, db: Session = Depends(get_db)):
    try:
        service = IngestService(db)
        result = service.ingest_text(req.title, req.content, req.source, req.tags)
        return success_response(IngestResultData(**result))
    except Exception as e:
        logger.error(f"Ingest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ingest/arxiv", tags=["docs"])
def ingest_arxiv(req: ArxivIngestRequest, db: Session = Depends(get_db)):
    try:
        result = ArxivImporter(db).import_paper(req.arxiv_id_or_url, prefer_html=req.prefer_html)
        return success_response(result)
    except Exception as e:
        logger.error(f"arXiv ingest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def extract_upload_text(filename: str, content: bytes) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        return extract_pdf_text(content)
    if lower.endswith(".docx"):
        return content.decode("latin1")
    if lower.endswith(".xlsx"):
        return content.decode("latin1")
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(f"Page {index}\n{page_text.strip()}")
        text_content = "\n\n".join(pages).strip()
        if text_content:
            return text_content
    except Exception as e:
        logger.warning(f"PDF text extraction failed: {e}")
    return content.decode("latin1", errors="ignore")


@app.post("/api/ingest/file", response_model=IngestResponse, tags=["docs"])
async def ingest_file(
    file: UploadFile = File(...),
    source: str = Form("file"),
    tags: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        content = await file.read()
        title = file.filename or "未命名文档"
        text_content = extract_upload_text(title, content)
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        service = IngestService(db)
        result = service.ingest_text(title, text_content, source, tag_list)
        return success_response(IngestResultData(**result))
    except Exception as e:
        logger.error(f"File ingest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/docs", response_model=DocsListResponse, tags=["docs"])
def list_docs(
    search: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    try:
        service = IngestService(db)
        docs, total = service.list_documents(search, source, limit, offset)
        return success_response(DocsListData(
            documents=[
                DocumentItem(
                    id=d.id,
                    title=d.title,
                    content_preview=d.content[:200] if d.content else "",
                    source=d.source,
                    tags=d.tags,
                    created_at=d.created_at.isoformat(),
                )
                for d in docs
            ],
            total=total,
            limit=limit,
            offset=offset,
        ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/docs/{doc_id}", response_model=DocDetailResponse, tags=["docs"])
def get_doc(doc_id: int, db: Session = Depends(get_db)):
    try:
        service = IngestService(db)
        doc = service.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        return success_response(DocDetailData(**doc))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/docs/{doc_id}/chunks", tags=["docs"])
def get_doc_chunks(
    doc_id: int,
    chunk_type: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        query = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        chunks = query.all()
        items = []
        for chunk in chunks:
            metadata = extract_chunk_metadata(chunk.content)
            if chunk_type and metadata.get("chunk_type") != chunk_type:
                continue
            items.append({
                "id": chunk.id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
                **metadata,
            })
        total = len(items)
        return success_response({
            "document": {"id": doc.id, "title": doc.title, "source": doc.source},
            "chunks": items[offset:offset + limit],
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/docs/{doc_id}", tags=["docs"])
def delete_doc(doc_id: int, db: Session = Depends(get_db)):
    try:
        service = IngestService(db)
        deleted = service.delete_document(doc_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="文档不存在")
        return success_response({}, "文档已删除")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/docs/{doc_id}/paper-graph", tags=["docs", "kg"])
def get_doc_paper_graph(
    doc_id: int,
    limit: int = 300,
    db: Session = Depends(get_db),
):
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")

        nodes = (
            db.query(Node)
            .filter(Node.source_doc_ids.contains([doc_id]))
            .limit(limit)
            .all()
        )
        if not nodes:
            nodes = db.query(Node).filter(Node.properties["document_id"].as_integer() == doc_id).limit(limit).all()
        node_ids = [node.id for node in nodes]
        edges = []
        if node_ids:
            edges = (
                db.query(Edge)
                .filter(Edge.source_id.in_(node_ids), Edge.target_id.in_(node_ids))
                .limit(limit * 2)
                .all()
            )

        return success_response({
            "document": {"id": doc.id, "title": doc.title, "source": doc.source},
            "nodes": [
                {
                    "id": node.id,
                    "name": node.name,
                    "type": node.type,
                    "description": node.description,
                    "properties": node.properties or {},
                    "confidence": node.confidence,
                }
                for node in nodes
            ],
            "edges": [
                {
                    "id": edge.id,
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                    "relation": edge.relation,
                    "type": edge.type,
                    "confidence": edge.confidence,
                }
                for edge in edges
            ],
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 知识图谱 API ──────────────────────────────────────────────────

@app.get("/api/kg/nodes", response_model=NodesListResponse, tags=["kg"])
def list_nodes(
    search: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    try:
        service = KGService(db)
        nodes, total = service.list_nodes(search, type, limit, offset)
        return success_response(NodesListData(
            nodes=[
                NodeItem(
                    id=n.id,
                    name=n.name,
                    type=n.type,
                    description=n.description,
                    source_doc_ids=n.source_doc_ids,
                    confidence=n.confidence,
                    created_at=n.created_at.isoformat() if n.created_at else None,
                )
                for n in nodes
            ],
            total=total,
        ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/kg/nodes", response_model=NodeCreateResponse, tags=["kg"])
def create_node(req: NodeCreateRequest, db: Session = Depends(get_db)):
    try:
        service = KGService(db)
        node = service.create_node(req.name, req.type, req.description, req.source_doc_ids)
        return success_response(NodeCreateData(
            id=node.id, name=node.name, type=node.type, message="节点创建成功"
        ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/kg/nodes/{node_id}", tags=["kg"])
def update_node(node_id: int, req: NodeUpdateRequest, db: Session = Depends(get_db)):
    try:
        service = KGService(db)
        node = service.update_node(node_id, req.name, req.description)
        if not node:
            raise HTTPException(status_code=404, detail="节点不存在")
        return success_response({"id": node.id, "name": node.name}, "节点更新成功")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/kg/nodes/{node_id}", tags=["kg"])
def delete_node(node_id: int, db: Session = Depends(get_db)):
    try:
        service = KGService(db)
        deleted = service.delete_node(node_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="节点不存在")
        return success_response({}, "节点已删除")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/kg/edges", response_model=EdgesListResponse, tags=["kg"])
def list_edges(
    source_id: Optional[int] = None,
    target_id: Optional[int] = None,
    relation: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    try:
        service = KGService(db)
        edges = service.list_edges(source_id, target_id, relation, limit)
        return success_response(EdgesListData(
            edges=[
                EdgeItem(
                    id=e.id,
                    source_id=e.source_id,
                    target_id=e.target_id,
                    relation=e.relation,
                    source_name=e.source_node.name if e.source_node else "",
                    target_name=e.target_node.name if e.target_node else "",
                    confidence=e.confidence,
                )
                for e in edges
            ]
        ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/kg/edges", response_model=EdgesListResponse, tags=["kg"])
def create_edge(req: EdgeCreateRequest, db: Session = Depends(get_db)):
    try:
        service = KGService(db)
        edge = service.create_edge(req.source_id, req.target_id, req.relation, req.confidence)
        if not edge:
            raise HTTPException(status_code=400, detail="关系创建失败或已存在")
        return success_response(EdgesListData(edges=[EdgeItem(
            id=edge.id, source_id=edge.source_id, target_id=edge.target_id,
            relation=edge.relation, confidence=edge.confidence,
        )]))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/kg/edges/{edge_id}", tags=["kg"])
def delete_edge(edge_id: int, db: Session = Depends(get_db)):
    try:
        service = KGService(db)
        deleted = service.delete_edge(edge_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="关系不存在")
        return success_response({}, "关系已删除")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/kg/search", response_model=KGSearchResponse, tags=["kg"])
def kg_search(
    q: str,
    mode: str = "hybrid",
    top_k: int = 10,
    db: Session = Depends(get_db),
):
    try:
        service = KGService(db)
        result = service.search(q, mode, top_k)
        return success_response(KGSearchData(
            entities=[KGSearchEntityItem(**e) for e in result["entities"]],
            relations=[KGSearchRelationItem(**r) for r in result["relations"]],
            mode=result["mode"],
        ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/kg/paper-graph/search", tags=["kg"])
def search_paper_graph(
    q: str,
    method: str = "subgraph",
    limit: int = 20,
    depth: int = 2,
    doc_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    try:
        if method not in {"ego", "path", "subgraph"}:
            raise HTTPException(status_code=400, detail="method 只能是 ego/path/subgraph")
        seed_node_ids: List[int] = []
        if doc_id:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if not doc:
                raise HTTPException(status_code=404, detail="文档不存在")
            paper_node = (
                db.query(Node)
                .filter(Node.type == "paper", Node.source_doc_ids.contains([doc_id]))
                .first()
            )
            if not paper_node:
                paper_node = db.query(Node).filter(Node.properties["document_id"].as_integer() == doc_id, Node.type == "paper").first()
            if paper_node:
                seed_node_ids.append(paper_node.id)
        results = GraphRetrievalService(db).search(
            method=method,
            entities=[],
            seed_node_ids=seed_node_ids,
            query=q,
            limit=limit,
            depth=depth,
        )
        return success_response({"query": q, "method": method, "doc_id": doc_id, "results": results})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/kg/graph", tags=["kg"])
def kg_graph(
    center_id: Optional[int] = None,
    depth: int = 1,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """获取图谱可视化数据"""
    try:
        service = KGService(db)
        result = service.get_graph_data(center_id, depth, limit)
        return success_response(GraphData(**result))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 对话管理 API ──────────────────────────────────────────────────

@app.get("/api/convs", response_model=ConvsListResponse, tags=["conversation"])
def list_convs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    try:
        service = RetrievalService(db)
        convs, total = service.list_conversations(limit, offset)
        return success_response(ConvsListData(
            conversations=[
                ConvItem(**service.format_conversation(c))
                for c in convs
            ]
        ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/convs/{conv_id}", response_model=ConvDetailResponse, tags=["conversation"])
def get_conv(conv_id: int, db: Session = Depends(get_db)):
    try:
        service = RetrievalService(db)
        conv = service.get_conversation(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")
        return success_response(ConvDetailData(
            id=conv.id,
            title=conv.title,
            messages=service.format_messages(conv),
        ))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/convs/{conv_id}", tags=["conversation"])
def delete_conv(conv_id: int, db: Session = Depends(get_db)):
    try:
        service = RetrievalService(db)
        deleted = service.delete_conversation(conv_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="对话不存在")
        return success_response({}, "对话已删除")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 设置 API ──────────────────────────────────────────────────────

AVAILABLE_PROVIDERS = ["dashscope", "openai", "anthropic", "deepseek"]

# 可用的模型映射
AVAILABLE_MODELS = {
    "dashscope": ["qwen-plus", "qwen-turbo", "qwen-max", "qwen-long"],
    "openai": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-3-opus", "claude-3-sonnet", "claude-3-haiku"],
    "deepseek": ["deepseek-chat", "deepseek-coder"],
}


@app.get("/api/settings", response_model=SettingsResponse, tags=["settings"])
def get_settings():
    """获取当前设置"""
    from llm.manager import llm_manager
    return success_response(SettingsData(
        provider=llm_manager.provider,
        model=llm_manager.model,
        temperature=llm_manager.temperature,
        embedding_model=config.OPENAI_EMBEDDING_MODEL,
        available_providers=AVAILABLE_PROVIDERS,
        available_models=AVAILABLE_MODELS.get(llm_manager.provider, []),
    ))


@app.put("/api/settings", response_model=SettingsResponse, tags=["settings"])
def update_settings(req: SettingsUpdateRequest):
    """更新设置（动态生效，无需重启）"""
    from llm.manager import llm_manager

    if req.provider and req.provider not in AVAILABLE_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"不支持的提供商。可选: {AVAILABLE_PROVIDERS}")

    try:
        updates = {}
        if req.provider:
            updates = llm_manager.update_settings(provider=req.provider, model=req.model, temperature=req.temperature)
        elif req.model or req.temperature is not None:
            updates = llm_manager.update_settings(model=req.model, temperature=req.temperature)

        # 保存到配置文件
        if req.provider:
            config.LLM_PROVIDER = req.provider
        if req.model:
            config.LLM_MODEL = req.model
        if req.temperature is not None:
            config.LLM_TEMPERATURE = req.temperature

        return success_response(SettingsData(
            provider=llm_manager.provider,
            model=llm_manager.model,
            temperature=llm_manager.temperature,
            embedding_model=config.OPENAI_EMBEDDING_MODEL,
            available_providers=AVAILABLE_PROVIDERS,
            available_models=AVAILABLE_MODELS.get(llm_manager.provider, []),
        ), "设置已更新并生效")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"设置更新失败: {str(e)}")


# ── 启动入口 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=False)
