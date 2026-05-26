import { useState, useEffect } from 'react';
import { getDoc, getDocChunks, getDocPaperGraph, getDocs, deleteDoc } from '../api/client';
import type { DocChunkItem, PaperGraphData } from '../types';

const CHUNK_TYPE_LABELS: Record<string, string> = {
  abstract: '摘要',
  method: '方法',
  experiment: '实验',
  table: '表格',
  code: '代码',
  equation: '公式',
  reference: '参考文献',
  related_work: '相关工作',
  conclusion: '结论',
  paragraph: '正文',
  chunk: '分片',
};

function chunkTypeLabel(type = '') {
  return CHUNK_TYPE_LABELS[type] || type || '分片';
}

export default function DocsPage() {
  const [docs, setDocs] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<any>(null);
  const [chunks, setChunks] = useState<DocChunkItem[]>([]);
  const [paperGraph, setPaperGraph] = useState<PaperGraphData | null>(null);
  const [chunkFilter, setChunkFilter] = useState('');
  const [detailLoading, setDetailLoading] = useState(false);

  const loadDocs = async () => {
    setLoading(true);
    try {
      const data = await getDocs(search || undefined, 20, 0);
      setDocs(data.documents || []);
      setTotal(data.total || 0);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadDocs(); }, []);

  const handleSearch = () => { loadDocs(); };

  const openDoc = async (id: number) => {
    setDetailLoading(true);
    setChunkFilter('');
    try {
      const [fullData, chunkData, graphData] = await Promise.all([
        getDoc(id),
        getDocChunks(id),
        getDocPaperGraph(id).catch(() => null),
      ]);
      setSelectedDoc(fullData || null);
      setChunks(chunkData.chunks || []);
      setPaperGraph(graphData);
    } catch (e) {
      console.error(e);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确认删除这篇文档？')) return;
    try {
      await deleteDoc(id);
      loadDocs();
      if (selectedDoc?.id === id) {
        setSelectedDoc(null);
        setChunks([]);
        setPaperGraph(null);
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="p-8 max-w-4xl mx-auto h-full flex flex-col">
      {/* 头部 */}
      <div className="mb-6 flex items-center gap-4">
        <div>
          <h1 className="font-display text-3xl text-text-primary">文档库</h1>
          <p className="font-mono text-xs tracking-label text-text-muted mt-1">
            知识库中共有 {total} 篇文档
          </p>
        </div>
        <div className="flex-1" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="搜索文档..."
          className="bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border
                     font-body text-sm focus:outline-none focus:border-brand/60 transition-colors"
        />
        <button
          onClick={handleSearch}
          className="bg-brand text-canvas px-5 py-2.5 rounded-lg font-body text-sm hover:bg-brand/90 active:scale-[0.98] transition-all"
        >
          搜索
        </button>
      </div>

      {/* 文档列表 */}
      <div className="flex-1 overflow-y-auto space-y-4">
        {loading ? (
          <div className="text-center py-20 font-mono text-xs tracking-label text-text-muted">
            加载中...
          </div>
        ) : docs.length === 0 ? (
          <div className="text-center py-20 font-mono text-xs tracking-label text-text-muted/50">
            暂无文档，导入一些知识吧
          </div>
        ) : (
          docs.map((doc: any) => (
            <div
              key={doc.id}
              className="bg-slate rounded-lg p-5 border border-border hover:border-text-muted transition-all cursor-pointer"
              onClick={() => openDoc(doc.id)}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="font-body text-text-primary font-medium truncate">{doc.title}</h3>
                    <span className="px-2.5 py-1 bg-canvas text-text-muted text-xs font-mono uppercase rounded-md border border-border flex-shrink-0">
                      {doc.source}
                    </span>
                  </div>
                  <p className="text-text-muted font-body text-sm line-clamp-2">
                    {doc.content_preview || '无预览内容'}
                  </p>
                  {doc.tags?.length > 0 && (
                    <div className="flex gap-2 mt-3">
                      {doc.tags.map((t: string, i: number) => (
                        <span key={i} className="px-2.5 py-1 bg-brand/10 text-brand text-xs font-mono uppercase rounded-md border border-brand/20">
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDelete(doc.id); }}
                  className="text-text-muted hover:text-danger text-sm font-mono px-2.5 py-1 rounded-md border border-border hover:border-danger/40 transition-all flex-shrink-0"
                >
                  删除
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* 文档详情弹窗 */}
      {selectedDoc && (
        <div
          className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-8"
          onClick={() => setSelectedDoc(null)}
        >
          <div
            className="bg-slate rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto p-6 border border-border"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex justify-between items-start mb-4">
              <h2 className="font-display text-2xl text-text-primary">{selectedDoc.title}</h2>
              <button
                onClick={() => setSelectedDoc(null)}
                className="text-text-muted hover:text-text-primary text-xl px-3 py-1"
              >
                ✕
              </button>
            </div>
            <div className="font-body text-text-secondary whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto border border-border-subtle rounded-lg p-4 bg-canvas/60">
              {selectedDoc.content}
            </div>

            {chunks.length > 0 && (
              <div className="mt-6 pt-4 border-t border-border space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-mono text-xs tracking-label text-text-muted">论文分片</div>
                    <div className="text-text-muted text-xs mt-1">{chunks.length} 个分片 · {Array.from(new Set(chunks.map(c => c.chunk_type).filter(Boolean))).length} 种类型</div>
                  </div>
                  <select
                    value={chunkFilter}
                    onChange={e => setChunkFilter(e.target.value)}
                    className="bg-canvas text-text-secondary border border-border rounded-lg px-3 py-2 text-xs font-mono"
                  >
                    <option value="">全部类型</option>
                    {Array.from(new Set(chunks.map(c => c.chunk_type).filter(Boolean))).map(type => <option key={type} value={type}>{chunkTypeLabel(type)}</option>)}
                  </select>
                </div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(chunks.reduce((acc: Record<string, number>, c) => {
                    const type = c.chunk_type || 'chunk';
                    acc[type] = (acc[type] || 0) + 1;
                    return acc;
                  }, {})).map(([type, count]) => (
                    <span key={type} className="px-2 py-1 bg-canvas border border-border rounded-md text-xs text-text-muted font-mono">{chunkTypeLabel(type)}: {count}</span>
                  ))}
                </div>
                <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
                  {chunks.filter(c => !chunkFilter || c.chunk_type === chunkFilter).slice(0, 30).map(chunk => (
                    <div key={chunk.id} className="p-3 bg-canvas/70 rounded-md border border-border-subtle">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="px-2 py-0.5 rounded-md bg-brand/10 border border-brand/30 text-brand text-xs font-mono">{chunkTypeLabel(chunk.chunk_type || 'chunk')}</span>
                        <span className="text-text-muted text-xs font-mono">#{chunk.chunk_index}</span>
                        {chunk.section_path && <span className="text-text-muted text-xs truncate">{chunk.section_path}</span>}
                      </div>
                      <p className="text-text-secondary text-sm leading-relaxed whitespace-pre-wrap line-clamp-5">{chunk.content}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {paperGraph && (
              <div className="mt-6 pt-4 border-t border-border">
                <div className="font-mono text-xs tracking-label text-text-muted mb-3">论文结构图</div>
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div className="p-3 bg-canvas rounded-md text-center"><div className="text-2xl font-display text-brand">{paperGraph.nodes?.length || 0}</div><div className="text-xs font-mono text-text-muted">节点</div></div>
                  <div className="p-3 bg-canvas rounded-md text-center"><div className="text-2xl font-display text-info">{paperGraph.edges?.length || 0}</div><div className="text-xs font-mono text-text-muted">关系</div></div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {(paperGraph.nodes || []).slice(0, 20).map(node => (
                    <span key={node.id} className="px-2 py-1 bg-canvas border border-border rounded-md text-xs text-text-muted">{node.type}:{node.name}</span>
                  ))}
                </div>
              </div>
            )}

            {selectedDoc.related_nodes?.length > 0 && (
              <div className="mt-6 pt-4 border-t border-border">
                <div className="font-mono text-xs tracking-label text-text-muted mb-3">关联节点</div>
                <div className="flex flex-wrap gap-2">
                  {selectedDoc.related_nodes.map((n: any, i: number) => (
                    <span key={i} className="px-2.5 py-1 bg-brand/10 text-brand text-xs rounded-md border border-brand/30">
                      {n.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
