// TypeScript 类型定义

export interface ExecutionStep {
  agent: string;
  step: string;
  elapsed: number;
  timestamp: number;
}

export interface ImportPaperAction {
  type: 'import_paper';
  label: string;
  requires_confirmation: boolean;
  reason?: string;
  paper: {
    title: string;
    url: string;
    source: string;
    arxiv_id?: string;
    snippet?: string;
    provider?: string;
    quality_score?: number;
  };
}

export interface ResearchAction {
  step?: number;
  action?: string;
  query?: string;
  reason?: string;
  tool_name?: string;
  observation_summary?: string;
  evidence_count?: number;
  status?: string;
  node?: string;
  next_node?: string;
  intent?: string;
  allowed_tools?: string[];
}

export interface EvidenceItem {
  id?: number | string;
  source_type?: string;
  title?: string;
  content?: string;
  citation?: string;
  score?: number;
  metadata?: {
    source?: string;
    provider?: string;
    url?: string;
    authors?: string;
    year?: string | number;
    chunk_type?: string;
    match_type?: string;
    paper_id?: string;
    original_id?: string;
    [key: string]: any;
  };
  [key: string]: any;
}

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
  sources?: SourceItem[];
  explanations?: ExplanationItem[];
  suggested_actions?: ImportPaperAction[];
  path?: string;
  processing_time?: string;
  confidence?: number;
  paper_task?: PaperTaskInfo;
  evidence_grade?: EvidenceGrade;
  retrieval_rounds?: RetrievalRound[];
  performance?: PerformanceMetrics;
  executionSteps?: ExecutionStep[];
  research_actions?: ResearchAction[];
  research_intent?: string;
  answer_verification?: Record<string, any>;
  citation_verification?: Record<string, any>;
  evidence_items?: EvidenceItem[];
}

export interface SourceItem {
  id: number | string;
  name: string;
  type: string;
  description?: string;
  chunk_type?: string;
  section_path?: string;
  source?: string;
  paper_title?: string;
  url?: string;
}

export interface ExplanationItem {
  term: string;
  simple: string;
  analogy?: string;
}

export interface Conversation {
  id: number;
  title?: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface KGNode {
  id: number;
  name: string;
  type: string;
  description?: string;
  group: number;
}

export interface KGLink {
  source: number;
  target: number;
  relation: string;
}

export interface GraphData {
  nodes: KGNode[];
  links: KGLink[];
}

export interface KGEdge {
  id: number;
  source_id: number;
  target_id: number;
  relation: string;
  source_name?: string;
  target_name?: string;
  confidence: number;
}

export interface SSEEvent {
  type: 'status' | 'delta' | 'sources' | 'explanations' | 'metrics' | 'error' | 'conversation_id';
  agent?: string;
  step?: string;
  elapsed?: number;
  content?: string;
  data?: any;
  path?: string;
  processing_time?: string;
  confidence?: number;
  message?: string;
  conversation_id?: number;
  suggested_actions?: ImportPaperAction[];
  paper_task?: PaperTaskInfo;
  evidence_grade?: EvidenceGrade;
  retrieval_rounds?: RetrievalRound[];
  performance?: PerformanceMetrics;
  research_actions?: ResearchAction[];
  research_intent?: string;
  answer_verification?: Record<string, any>;
  citation_verification?: Record<string, any>;
  evidence_items?: EvidenceItem[];
}

export interface PaperTaskInfo {
  task_type?: string;
  answer_style?: string;
  preferred_chunk_types?: string[];
  retrieval_override?: Record<string, any>;
  reason?: string;
  expert?: string;
}

export interface EvidenceGrade {
  relevance_score?: number;
  support_score?: number;
  coverage_score?: number;
  freshness_required?: boolean;
  conflict_detected?: boolean;
  sufficient?: boolean;
  missing_aspects?: string[];
  next_action?: string;
  reason?: string;
}

export interface RetrievalRound {
  round?: number;
  query?: string;
  source?: string;
  repair?: Record<string, any>;
  grade?: EvidenceGrade;
  retrieval?: {
    bm25_hits?: number;
    semantic_hits?: number;
    graph_hits?: number;
    merged?: number;
    chunk_types?: string[];
  };
}

export interface PerformanceMetrics {
  routing?: number;
  retrieval?: number;
  grading?: number;
  repair?: number;
  context?: number;
  generation?: number;
  sources?: number;
  total?: number;
  [key: string]: number | undefined;
}

export interface DocChunkItem {
  id: number;
  document_id: number;
  chunk_index: number;
  content: string;
  token_count?: number;
  created_at?: string;
  chunk_type?: string;
  section_path?: string;
  paper_title?: string;
  authors?: string;
  year?: string;
  method_name?: string;
  metric?: string;
  dataset?: string;
}

export interface PaperGraphNode {
  id: number;
  name: string;
  type: string;
  description?: string;
  properties?: Record<string, any>;
  confidence?: number;
}

export interface PaperGraphEdge {
  id: number;
  source_id: number;
  target_id: number;
  relation: string;
  type?: string;
  confidence?: number;
}

export interface PaperGraphData {
  document?: { id: number; title: string; source?: string };
  nodes: PaperGraphNode[];
  edges: PaperGraphEdge[];
}

export interface AppSettings {
  provider: string;
  model: string;
  temperature: number;
  embedding_model: string;
  available_providers: string[];
}

export interface HealthStatus {
  status: string;
  database: string;
  llm: string;
  web_search: string;
  version: string;
}
