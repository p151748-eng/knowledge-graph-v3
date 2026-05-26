// TypeScript 类型定义

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
  sources?: SourceItem[];
  explanations?: ExplanationItem[];
  path?: string;
  processing_time?: string;
  confidence?: number;
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
  paper_task?: PaperTaskInfo;
  evidence_grade?: EvidenceGrade;
  retrieval_rounds?: RetrievalRound[];
  performance?: PerformanceMetrics;
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
