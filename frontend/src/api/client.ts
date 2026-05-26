import axios from 'axios';
import type {
  Message, SourceItem, ExplanationItem,
  Conversation, GraphData, AppSettings, HealthStatus,
  DocChunkItem, PaperGraphData
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || '';

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
});

// ── 通用响应解析 ──────────────────────────────────────────────────

function extractData(response: any) {
  return response.data?.data ?? response.data;
}

// ── Chat ──────────────────────────────────────────────────────────

export async function chat(message: string, conversationId?: number) {
  const res = await client.post('/api/chat', { message, conversation_id: conversationId });
  return extractData(res);
}

export async function chatPaper(message: string, conversationId?: number) {
  const res = await client.post('/api/chat/paper', { message, conversation_id: conversationId });
  return extractData(res);
}

export async function chatStream(message: string, conversationId?: number, chatPath?: string): Promise<ReadableStream> {
  const response = await fetch(`${BASE_URL}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId, chat_path: chatPath }),
  });
  if (!response.ok) {
    throw new Error(`聊天接口请求失败：${response.status}`);
  }
  if (!response.body) {
    throw new Error('聊天接口没有返回可读取的数据流');
  }
  return response.body;
}

// ── Web Search ────────────────────────────────────────────────────

export async function webSearch(query: string, save = true) {
  const res = await client.post('/api/websearch', {
    query,
    save_to_kg: save,
    save_to_docs: save,
    max_results: 5,
  });
  return extractData(res);
}

// ── Docs ──────────────────────────────────────────────────────────

export async function ingestDocument(title: string, content: string, tags?: string[]) {
  const res = await client.post('/api/ingest', { title, content, tags, source: 'manual' });
  return extractData(res);
}

export async function ingestArxiv(arxivIdOrUrl: string, preferHtml = true) {
  const res = await client.post('/api/ingest/arxiv', { arxiv_id_or_url: arxivIdOrUrl, prefer_html: preferHtml });
  return extractData(res);
}

export async function ingestFile(file: File, tags?: string) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('source', 'file');
  formData.append('tags', tags || '');
  const res = await client.post('/api/ingest/file', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return extractData(res);
}

export async function getDocs(search?: string, limit = 20, offset = 0) {
  const res = await client.get('/api/docs', { params: { search, limit, offset } });
  return extractData(res);
}

export async function getDoc(docId: number) {
  const res = await client.get(`/api/docs/${docId}`);
  return extractData(res);
}

export async function getDocChunks(docId: number, chunkType?: string, limit = 200, offset = 0): Promise<{ document: any; chunks: DocChunkItem[]; total: number }> {
  const res = await client.get(`/api/docs/${docId}/chunks`, { params: { chunk_type: chunkType, limit, offset } });
  return extractData(res);
}

export async function getDocPaperGraph(docId: number): Promise<PaperGraphData> {
  const res = await client.get(`/api/docs/${docId}/paper-graph`);
  return extractData(res);
}

export async function deleteDoc(docId: number) {
  const res = await client.delete(`/api/docs/${docId}`);
  return extractData(res);
}

// ── KG ────────────────────────────────────────────────────────────

export async function getKGNodes(search?: string, type?: string, limit = 100) {
  const res = await client.get('/api/kg/nodes', { params: { search, type, limit } });
  return extractData(res);
}

export async function createKGNode(name: string, type = 'entity', description?: string) {
  const res = await client.post('/api/kg/nodes', { name, type, description });
  return extractData(res);
}

export async function updateKGNode(nodeId: number, name?: string, description?: string) {
  const res = await client.put(`/api/kg/nodes/${nodeId}`, { name, description });
  return extractData(res);
}

export async function deleteKGNode(nodeId: number) {
  const res = await client.delete(`/api/kg/nodes/${nodeId}`);
  return extractData(res);
}

export async function searchKG(q: string, mode = 'hybrid', top_k = 10) {
  const res = await client.get('/api/kg/search', { params: { q, mode, top_k } });
  return extractData(res);
}

export async function getKGGraph(centerId?: number, depth = 1, limit = 100): Promise<GraphData> {
  const res = await client.get('/api/kg/graph', { params: { center_id: centerId, depth, limit } });
  return extractData(res);
}

export async function searchPaperGraph(q: string, method = 'subgraph', docId?: number, limit = 20, depth = 2) {
  const res = await client.get('/api/kg/paper-graph/search', { params: { q, method, doc_id: docId, limit, depth } });
  return extractData(res);
}

// ── KG Edges ─────────────────────────────────────────────────────

export async function getKGEdges(sourceId?: number, targetId?: number, limit = 200) {
  const res = await client.get('/api/kg/edges', { params: { source_id: sourceId, target_id: targetId, limit } });
  return extractData(res);
}

export async function createKGEdge(sourceId: number, targetId: number, relation: string, confidence = 0.8) {
  const res = await client.post('/api/kg/edges', { source_id: sourceId, target_id: targetId, relation, confidence });
  return extractData(res);
}

export async function deleteKGEdge(edgeId: number) {
  const res = await client.delete(`/api/kg/edges/${edgeId}`);
  return extractData(res);
}

// ── Conversations ─────────────────────────────────────────────────

export async function getConversations() {
  const res = await client.get('/api/convs');
  return extractData(res);
}

export async function getConversation(convId: number) {
  const res = await client.get(`/api/convs/${convId}`);
  return extractData(res);
}

export async function deleteConversation(convId: number) {
  const res = await client.delete(`/api/convs/${convId}`);
  return extractData(res);
}

// ── Settings ─────────────────────────────────────────────────────

export async function getSettings(): Promise<AppSettings> {
  const res = await client.get('/api/settings');
  return extractData(res);
}

export async function updateSettings(settings: Partial<AppSettings>) {
  const res = await client.put('/api/settings', settings);
  return extractData(res);
}

// ── Health ────────────────────────────────────────────────────────

export async function getHealth(): Promise<HealthStatus> {
  const res = await client.get('/api/health');
  return extractData(res);
}
