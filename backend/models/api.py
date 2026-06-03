from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Chat ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    conversation_id: Optional[int] = Field(None, description="继续已有对话的ID")
    force_path: Optional[str] = Field(None, description="强制路径: fast/pipeline/paper/self_rag/crag")
    chat_path: Optional[str] = Field(None, description="前端路径选择: auto/fast/pipeline/paper/self_rag/crag")


class SourceItem(BaseModel):
    id: Any
    name: str
    type: str
    description: Optional[str] = None
    chunk_type: Optional[str] = None
    section_path: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[str] = None
    paper_id: Optional[str] = None
    provider: Optional[str] = None
    citation: Optional[str] = None


class ExplanationItem(BaseModel):
    term: str
    simple: str
    analogy: Optional[str] = None


class ChatData(BaseModel):
    response: str
    sources: List[SourceItem] = Field(default_factory=list)
    explanations: Optional[List[ExplanationItem]] = None
    conversation_id: int
    path: str
    processing_time: str
    confidence: Optional[float] = None


class ChatResponse(BaseModel):
    success: bool = True
    data: ChatData
    message: str = "操作成功"


# ── Web Search ──────────────────────────────────────────────────────

class WebSearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询")
    max_results: int = Field(5, description="最大结果数")
    save_to_kg: bool = Field(True, description="是否存入知识图谱")
    save_to_docs: bool = Field(True, description="是否存入文档库")


class SearchResultItem(BaseModel):
    title: str
    url: str
    snippet: str
    authors: Optional[str] = None
    year: Optional[str] = None
    source: Optional[str] = None
    provider: Optional[str] = None
    paper_id: Optional[str] = None
    quality_score: Optional[float] = None


class WebSearchData(BaseModel):
    results: List[SearchResultItem]
    saved_to_kg: bool = False
    saved_to_docs: bool = False
    nodes_created: int = 0
    edges_created: int = 0
    docs_created: int = 0
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


class WebSearchResponse(BaseModel):
    success: bool = True
    data: WebSearchData
    message: str = "操作成功"


# ── Document ───────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档内容")
    source: str = Field("manual", description="来源标识")
    tags: Optional[List[str]] = Field(None, description="标签")


class ArxivIngestRequest(BaseModel):
    arxiv_id_or_url: str = Field(..., description="arXiv ID 或 URL")
    prefer_html: bool = Field(True, description="优先导入 HTML 全文，失败时回退摘要页")


class DocumentItem(BaseModel):
    id: int
    title: str
    content_preview: str
    source: str
    tags: Optional[List[str]] = None
    created_at: str


class DocsListData(BaseModel):
    documents: List[DocumentItem]
    total: int
    limit: int
    offset: int = 0


class DocsListResponse(BaseModel):
    success: bool = True
    data: DocsListData


class DocDetailData(BaseModel):
    id: int
    title: str
    content: str
    source: str
    source_url: Optional[str] = None
    tags: Optional[List[str]] = None
    related_nodes: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str


class DocDetailResponse(BaseModel):
    success: bool = True
    data: DocDetailData


class IngestResultData(BaseModel):
    document_id: int
    nodes_created: int
    edges_created: int
    entities_extracted: List[Dict[str, Any]] = Field(default_factory=list)
    message: str


class IngestResponse(BaseModel):
    success: bool = True
    data: IngestResultData


# ── KG ──────────────────────────────────────────────────────────────

class NodeItem(BaseModel):
    id: int
    name: str
    type: str
    description: Optional[str] = None
    source_doc_ids: Optional[List[int]] = None
    confidence: float = 0.8
    created_at: Optional[str] = None


class NodesListData(BaseModel):
    nodes: List[NodeItem]
    total: int


class NodesListResponse(BaseModel):
    success: bool = True
    data: NodesListData


class NodeCreateRequest(BaseModel):
    name: str
    type: str = "entity"
    description: Optional[str] = None
    source_doc_ids: Optional[List[int]] = None


class NodeUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class NodeCreateData(BaseModel):
    id: int
    name: str
    type: str
    message: str


class NodeCreateResponse(BaseModel):
    success: bool = True
    data: NodeCreateData


class EdgeItem(BaseModel):
    id: int
    source_id: int
    target_id: int
    relation: str
    source_name: Optional[str] = None
    target_name: Optional[str] = None
    confidence: float = 0.8


class EdgesListData(BaseModel):
    edges: List[EdgeItem]


class EdgesListResponse(BaseModel):
    success: bool = True
    data: EdgesListData


class EdgeCreateRequest(BaseModel):
    source_id: int
    target_id: int
    relation: str
    confidence: float = 0.8


class KGSearchRequest(BaseModel):
    q: str = Field(..., description="搜索查询")
    mode: str = Field("hybrid", description="检索模式: keyword/semantic/hybrid")
    top_k: int = Field(10, description="返回数量")


class KGSearchEntityItem(BaseModel):
    id: int
    name: str
    type: str
    description: Optional[str] = None
    score: float
    match_type: str


class KGSearchRelationItem(BaseModel):
    source: str
    relation: str
    target: str


class KGSearchData(BaseModel):
    entities: List[KGSearchEntityItem]
    relations: List[KGSearchRelationItem]
    mode: str


class KGSearchResponse(BaseModel):
    success: bool = True
    data: KGSearchData


# ── KG Graph（可视化） ─────────────────────────────────────────────

class GraphNode(BaseModel):
    id: int
    name: str
    type: str
    group: int
    description: Optional[str] = None


class GraphLink(BaseModel):
    source: int
    target: int
    relation: str


class GraphData(BaseModel):
    nodes: List[GraphNode]
    links: List[GraphLink]


# ── Conversation ───────────────────────────────────────────────────

class MessageItem(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None


class ConvItem(BaseModel):
    id: int
    title: Optional[str] = None
    message_count: int
    created_at: str
    updated_at: str


class ConvsListData(BaseModel):
    conversations: List[ConvItem]


class ConvsListResponse(BaseModel):
    success: bool = True
    data: ConvsListData


class ConvDetailData(BaseModel):
    id: int
    title: Optional[str] = None
    messages: List[MessageItem]


class ConvDetailResponse(BaseModel):
    success: bool = True
    data: ConvDetailData


# ── Settings ────────────────────────────────────────────────────────

class SettingsData(BaseModel):
    provider: str
    model: str
    temperature: float
    embedding_model: str
    available_providers: List[str]
    available_models: List[str] = Field(default_factory=list)


class SettingsResponse(BaseModel):
    success: bool = True
    data: SettingsData


class SettingsUpdateRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None


# ── Health ─────────────────────────────────────────────────────────

class HealthData(BaseModel):
    status: str
    database: str
    llm: str
    web_search: str
    version: str


class HealthResponse(BaseModel):
    success: bool = True
    data: HealthData


# ── 通用错误 ──────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
