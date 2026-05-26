import { useState, useEffect, useRef } from 'react';
import {
  getKGGraph, createKGNode, deleteKGNode, updateKGNode,
  getKGNodes, searchKG,
  getKGEdges, createKGEdge, deleteKGEdge, searchPaperGraph,
} from '../api/client';
import type { GraphData, KGNode, KGEdge } from '../types';

// ForceGraph2D 动态导入
import ForceGraph2D from 'react-force-graph-2d';

const TYPE_COLORS: Record<string, string> = {
  concept: '#6db88f',
  entity: '#6b8aed',
  document: '#d97757',
};

const TYPE_LABELS: Record<string, string> = {
  concept: '概念',
  entity: '实体',
  document: '文档',
};

const GRAPH_METHOD_LABELS: Record<string, string> = {
  ego: '自我网络',
  path: '路径查找',
  subgraph: '子图提取',
};

function typeLabel(type = '') {
  return TYPE_LABELS[type] || type;
}

function graphMethodLabel(method = '') {
  return GRAPH_METHOD_LABELS[method] || method;
}

function nodeDegree(links: any[], nodeId: number | string) {
  return links.filter((l: any) => {
    const s = typeof l.source === 'object' ? (l.source as any).id : l.source;
    const t = typeof l.target === 'object' ? (l.target as any).id : l.target;
    return s === nodeId || t === nodeId;
  }).length;
}

export default function KGPage() {
  const [view, setView] = useState<'list' | 'graph'>('list');
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [selectedNode, setSelectedNode] = useState<KGNode | null>(null);
  const [nodes, setNodes] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [centerId, setCenterId] = useState<number | undefined>(undefined);
  const [newNodeName, setNewNodeName] = useState('');
  const [newNodeType, setNewNodeType] = useState('entity');
  const [showCreate, setShowCreate] = useState(false);
  // 边管理
  const [edges, setEdges] = useState<KGEdge[]>([]);
  const [showEdgePanel, setShowEdgePanel] = useState(false);
  const [showEdgeCreate, setShowEdgeCreate] = useState(false);
  const [newEdgeSource, setNewEdgeSource] = useState('');
  const [newEdgeTarget, setNewEdgeTarget] = useState('');
  const [newEdgeRelation, setNewEdgeRelation] = useState('');
  const [sourceSearch, setSourceSearch] = useState<any[]>([]);
  const [targetSearch, setTargetSearch] = useState<any[]>([]);

  // 搜索功能
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [paperGraphResults, setPaperGraphResults] = useState<any[]>([]);
  const [paperGraphMethod, setPaperGraphMethod] = useState('subgraph');
  const [paperGraphDocId, setPaperGraphDocId] = useState('');
  const [isSearching, setIsSearching] = useState(false);

  // 图谱控制
  const [linkDistance, setLinkDistance] = useState(80);
  const [showLabels, setShowLabels] = useState(true);
  const graphRef = useRef<any>(null);

  const loadGraph = async (cid?: number) => {
    setLoading(true);
    try {
      const data = await getKGGraph(cid, 1, 150);
      setGraphData(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const loadNodes = async () => {
    try {
      const data = await getKGNodes(undefined, undefined, 100);
      setNodes(data.nodes || []);
      setTotal(data.total || 0);
    } catch (e) {
      console.error(e);
    }
  };

  const loadEdges = async () => {
    try {
      const data = await getKGEdges();
      setEdges(data.edges || []);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (view === 'graph') {
      loadGraph(centerId);
    } else {
      loadNodes();
    }
  }, [view, centerId]);

  // 搜索节点
  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      setPaperGraphResults([]);
      return;
    }
    setIsSearching(true);
    try {
      const data = await searchKG(searchQuery, 'hybrid', 20);
      setSearchResults(data.entities || []);
      const graph = await searchPaperGraph(searchQuery, paperGraphMethod, paperGraphDocId ? Number(paperGraphDocId) : undefined, 20, 2);
      setPaperGraphResults(graph.results || []);
    } catch (e) {
      console.error(e);
    } finally {
      setIsSearching(false);
    }
  };

  const handleCreateNode = async () => {
    if (!newNodeName.trim()) return;
    try {
      await createKGNode(newNodeName.trim(), newNodeType);
      setNewNodeName('');
      setShowCreate(false);
      loadNodes();
      loadGraph(centerId);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteNode = async (id: number) => {
    if (!confirm('确认删除此节点？')) return;
    try {
      await deleteKGNode(id);
      loadNodes();
      loadGraph(centerId);
      loadEdges();
      if (selectedNode?.id === id) setSelectedNode(null);
    } catch (e) {
      console.error(e);
    }
  };

  const handleCreateEdge = async () => {
    if (!newEdgeSource || !newEdgeTarget || !newEdgeRelation.trim()) return;
    try {
      await createKGEdge(Number(newEdgeSource), Number(newEdgeTarget), newEdgeRelation.trim());
      setShowEdgeCreate(false);
      setNewEdgeSource('');
      setNewEdgeTarget('');
      setNewEdgeRelation('');
      loadEdges();
      loadGraph(centerId);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteEdge = async (id: number) => {
    if (!confirm('确认删除此关系？')) return;
    try {
      await deleteKGEdge(id);
      loadEdges();
      loadGraph(centerId);
    } catch (e) {
      console.error(e);
    }
  };

  const handleNodeSearch = async (query: string, setter: (v: any[]) => void) => {
    if (!query.trim()) { setter([]); return; }
    try {
      const data = await searchKG(query, 'hybrid', 10);
      setter(data.entities || []);
    } catch {}
  };

  const handleExpandNode = (node: KGNode) => {
    setSelectedNode(node);
    setCenterId(node.id);
    loadGraph(node.id);
  };

  const handleSearchResultClick = (entity: any) => {
    // 找到对应的节点并展开
    const node = nodes.find(n => n.name === entity.name);
    if (node) {
      handleExpandNode(node);
    } else {
      setCenterId(entity.id);
      loadGraph(entity.id);
    }
    setView('graph');
  };

  return (
    <div className="h-full flex flex-col">
      {/* 顶部工具栏 */}
      <div className="p-6 border-b border-border flex items-center gap-4 flex-wrap">
        <h1 className="font-display text-3xl text-text-primary">知识图谱</h1>
        <p className="font-mono text-xs tracking-label text-text-muted">
          {total} 个节点
        </p>
        <div className="flex-1" />

        {/* 搜索框 */}
        <div className="flex items-center gap-2">
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="搜索节点..."
            className="bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border font-body text-sm
                       focus:outline-none focus:border-brand/60 transition-colors w-48"
          />
          <select
            value={paperGraphMethod}
            onChange={e => setPaperGraphMethod(e.target.value)}
            className="bg-canvas text-text-secondary px-3 py-2.5 rounded-lg border border-border font-mono text-xs"
          >
            <option value="ego">自我网络</option>
            <option value="path">路径查找</option>
            <option value="subgraph">子图提取</option>
          </select>
          <input
            value={paperGraphDocId}
            onChange={e => setPaperGraphDocId(e.target.value)}
            placeholder="文档ID"
            className="bg-canvas text-text-primary px-3 py-2.5 rounded-lg border border-border font-body text-sm focus:outline-none focus:border-brand/60 transition-colors w-24"
          />
          <button
            onClick={handleSearch}
            disabled={isSearching}
            className="bg-slate text-text-secondary px-4 py-2.5 rounded-lg border border-border font-mono text-xs hover:text-text-primary hover:border-text-muted transition-all"
          >
            {isSearching ? '...' : '🔍'}
          </button>
        </div>

        {/* 视图切换 */}
        <div className="flex bg-slate rounded-lg border border-border overflow-hidden">
          <button
            onClick={() => setView('list')}
            className={`px-5 py-2.5 font-mono text-xs tracking-label transition-all ${
              view === 'list' ? 'bg-brand text-canvas' : 'text-text-muted hover:text-text-primary'
            }`}
          >
            列表
          </button>
          <button
            onClick={() => setView('graph')}
            className={`px-5 py-2.5 font-mono text-xs tracking-label transition-all ${
              view === 'graph' ? 'bg-brand text-canvas' : 'text-text-muted hover:text-text-primary'
            }`}
          >
            图谱
          </button>
        </div>

        <button
          onClick={() => { setShowEdgePanel(true); loadEdges(); }}
          className="bg-slate text-text-secondary px-5 py-2.5 rounded-lg font-mono text-xs tracking-label border border-border hover:border-text-muted transition-all"
        >
          关系管理
        </button>

        <button
          onClick={() => setShowCreate(true)}
          className="bg-brand text-canvas px-5 py-2.5 rounded-lg font-mono text-xs tracking-label hover:bg-brand/90 active:scale-[0.98] transition-all"
        >
          + 新建节点
        </button>

        {view === 'graph' && centerId && (
          <button
            onClick={() => { setCenterId(undefined); setSelectedNode(null); loadGraph(); }}
            className="bg-slate text-text-secondary px-5 py-2.5 rounded-lg font-mono text-xs tracking-label border border-border hover:border-text-muted"
          >
            重置
          </button>
        )}
      </div>

      {/* 搜索结果 */}
      {searchResults.length > 0 && (
        <div className="px-6 py-3 bg-info/10 border-b border-info/20">
          <div className="flex items-center justify-between mb-2">
            <span className="font-mono text-xs tracking-label text-info">
              搜索结果: {searchResults.length} 个
            </span>
            <button onClick={() => setSearchResults([])} className="text-text-muted hover:text-text-primary text-sm">✕</button>
          </div>
          <div className="flex flex-wrap gap-2">
            {searchResults.map((e, i) => (
              <button
                key={i}
                onClick={() => handleSearchResultClick(e)}
                className="px-2.5 py-1 bg-info/20 text-info text-xs rounded-md border border-info/40 hover:bg-info/30 transition-all"
              >
                {e.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {paperGraphResults.length > 0 && (
        <div className="px-6 py-3 bg-brand/10 border-b border-brand/20">
          <div className="flex items-center justify-between mb-2">
            <span className="font-mono text-xs tracking-label text-brand">
              论文图谱: {graphMethodLabel(paperGraphMethod)} · {paperGraphResults.length} 条
            </span>
            <button onClick={() => setPaperGraphResults([])} className="text-text-muted hover:text-text-primary text-sm">✕</button>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {paperGraphResults.slice(0, 8).map((item, i) => (
              <div key={i} className="p-3 bg-canvas/60 border border-border rounded-md text-xs text-text-muted">
                <div className="font-mono text-brand/80 mb-1">{item.result_type || item.type || 'paper_graph'}</div>
                <div>{item.description || item.name || JSON.stringify(item).slice(0, 180)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 列表视图 */}
      {view === 'list' && (
        <div className="flex-1 overflow-y-auto p-6 space-y-3">
          {nodes.map((n: any) => (
            <div key={n.id}
                 className="bg-slate rounded-lg p-5 border border-border flex items-center gap-4 hover:border-text-muted transition-all">
              <div
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ backgroundColor: TYPE_COLORS[n.type] || '#a89e95' }}
              />
              <div className="flex-1 min-w-0">
                <div className="font-body text-text-primary font-medium">{n.name}</div>
                {n.description && (
                  <div className="text-text-muted text-sm font-body truncate mt-1">{n.description}</div>
                )}
              </div>
              <span className="font-mono text-xs tracking-label text-text-muted border border-border px-2.5 py-1 rounded-md flex-shrink-0">
                {typeLabel(n.type)}
              </span>
              <div className="flex gap-2 flex-shrink-0">
                <button
                  onClick={() => handleExpandNode(n)}
                  className="px-2.5 py-1 text-xs font-mono uppercase border border-info/40 text-info rounded-md hover:bg-info/20"
                >
                  展开
                </button>
                <button
                  onClick={() => handleDeleteNode(n.id)}
                  className="px-2.5 py-1 text-xs font-mono uppercase border border-border text-text-muted rounded-md hover:text-danger hover:border-danger/40"
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 图谱视图 */}
      {view === 'graph' && (
        <div className="flex-1 relative flex">
          {/* 图谱控制面板 */}
          <div className="absolute left-4 top-4 z-10 bg-slate/90 backdrop-blur p-4 rounded-lg border border-border space-y-3">
            <div className="font-mono text-xs tracking-label text-text-secondary mb-2">图谱控制</div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-text-muted">距离</span>
              <input
                type="range"
                min="30"
                max="200"
                value={linkDistance}
                onChange={e => setLinkDistance(parseInt(e.target.value))}
                className="w-20 accent-brand"
              />
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={showLabels}
                onChange={e => setShowLabels(e.target.checked)}
                className="accent-brand"
              />
              <span className="font-mono text-xs text-text-secondary">显示标签</span>
            </label>
          </div>

          <div className="flex-1 relative">
            {loading ? (
              <div className="flex items-center justify-center h-full font-mono text-xs tracking-label text-text-muted">
                加载图谱...
              </div>
            ) : (
              <>
                <ForceGraph2D
                  ref={graphRef}
                  graphData={graphData as any}
                  backgroundColor="#1a1614"
                  nodeLabel="name"
                  nodeColor={(node: any) => TYPE_COLORS[node.type] || '#a89e95'}
                  nodeVal={(node: any) => {
                    const degree = nodeDegree(graphData.links, node.id);
                    return Math.max(4, Math.min(20, 4 + degree * 2));
                  }}
                  linkColor={() => 'rgba(168,158,149,0.12)'}
                  linkWidth={1}
                  linkDirectionalArrowLength={4}
                  linkDirectionalArrowRelPos={1}
                  linkDirectionalParticles={2}
                  linkDirectionalParticleSpeed={0.005}
                  onNodeClick={(node: any) => setSelectedNode(node)}
                  nodeCanvasObject={(node: any, ctx, globalScale) => {
                    const degree = nodeDegree(graphData.links, node.id);
                    const size = Math.max(4, Math.min(20, 4 + degree * 2));
                    const color = TYPE_COLORS[node.type] || '#a89e95';

                    ctx.beginPath();
                    ctx.arc(node.x!, node.y!, size, 0, 2 * Math.PI);
                    ctx.fillStyle = color;
                    ctx.fill();
                    ctx.strokeStyle = 'rgba(237,232,227,0.13)';
                    ctx.lineWidth = 1;
                    ctx.stroke();

                    if (showLabels && globalScale > 0.7) {
                      ctx.font = `${10 / globalScale}px "DM Sans", Helvetica, sans-serif`;
                      ctx.textAlign = 'center';
                      ctx.textBaseline = 'middle';
                      ctx.fillStyle = '#ede8e3';
                      ctx.fillText(node.name, node.x!, node.y! + size + 3);
                    }
                  }}
                  cooldownTicks={80}
                  onEngineStop={() => graphRef.current?.zoomToFit(400, 40)}
                  minZoom={0.1}
                  maxZoom={4}
                  d3VelocityDecay={0.3}
                />

                {/* 图例 */}
                <div className="absolute bottom-4 right-4 bg-slate/90 backdrop-blur px-4 py-3 rounded-lg border border-border flex gap-4">
                  {Object.entries(TYPE_COLORS).map(([type, color]) => (
                    <div key={type} className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
                      <span className="font-mono text-xs tracking-label text-text-secondary">{typeLabel(type)}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* 节点详情面板 */}
          {selectedNode && (
            <div className="w-80 bg-slate border-l border-border p-6 overflow-y-auto z-10">
              <div className="flex justify-between items-start mb-4">
                <span
                  className="font-mono text-xs tracking-label px-2.5 py-1 rounded-md border"
                  style={{
                    borderColor: TYPE_COLORS[selectedNode.type],
                    color: TYPE_COLORS[selectedNode.type],
                  }}
                >
                  {typeLabel(selectedNode.type)}
                </span>
                <button onClick={() => setSelectedNode(null)} className="text-text-muted hover:text-text-primary">✕</button>
              </div>
              <h2 className="font-display text-2xl text-text-primary mb-3">{selectedNode.name}</h2>
              <p className="font-body text-sm text-text-secondary leading-relaxed mb-6">
                {selectedNode.description || '暂无描述'}
              </p>
              <div className="space-y-3">
                <button
                  onClick={() => handleExpandNode(selectedNode)}
                  className="w-full bg-info/20 text-info px-4 py-2.5 rounded-lg font-mono text-xs tracking-label border border-info/40 hover:bg-info/30 transition-all"
                >
                  展开邻居节点
                </button>
                <button
                  onClick={() => handleDeleteNode(selectedNode.id)}
                  className="w-full bg-slate text-text-secondary px-4 py-2.5 rounded-lg font-mono text-xs tracking-label border border-border hover:border-danger/40 transition-all"
                >
                  删除节点
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 创建节点弹窗 */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-8"
             onClick={() => setShowCreate(false)}>
          <div
            className="bg-slate rounded-lg p-6 w-full max-w-md border border-border space-y-4"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="font-display text-2xl text-text-primary">新建节点</h3>
            <input
              value={newNodeName}
              onChange={e => setNewNodeName(e.target.value)}
              placeholder="节点名称..."
              autoFocus
              className="w-full bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border font-body text-sm focus:outline-none focus:border-brand/60"
            />
            <div className="flex gap-2">
              {['concept', 'entity', 'document'].map(t => (
                <button
                  key={t}
                  onClick={() => setNewNodeType(t)}
                  className={`flex-1 py-2.5 rounded-lg font-mono text-xs tracking-label border transition-all ${
                    newNodeType === t
                      ? 'text-canvas border-transparent'
                      : 'text-text-muted border-border hover:border-text-muted'
                  }`}
                  style={{ backgroundColor: newNodeType === t ? TYPE_COLORS[t] : undefined }}
                >
                  {typeLabel(t)}
                </button>
              ))}
            </div>
            <div className="flex gap-3">
              <button onClick={() => setShowCreate(false)}
                      className="flex-1 py-2.5 rounded-lg font-mono text-xs border border-border text-text-muted hover:border-text-muted">
                取消
              </button>
              <button
                onClick={handleCreateNode}
                className="flex-1 bg-brand text-canvas py-2.5 rounded-lg font-mono text-xs hover:bg-brand/90 active:scale-[0.98] transition-all"
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 边管理面板 */}
      {showEdgePanel && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-8"
             onClick={() => setShowEdgePanel(false)}>
          <div
            className="bg-slate rounded-lg p-6 w-full max-w-2xl border border-border max-h-[80vh] flex flex-col"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-6">
              <h3 className="font-display text-2xl text-text-primary">关系管理</h3>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowEdgeCreate(true)}
                  className="bg-brand text-canvas px-4 py-2.5 rounded-lg font-mono text-xs hover:bg-brand/90 active:scale-[0.98] transition-all"
                >
                  + 新建关系
                </button>
                <button onClick={() => setShowEdgePanel(false)} className="text-text-muted hover:text-text-primary text-xl">✕</button>
              </div>
            </div>

            {showEdgeCreate && (
              <div className="mb-6 p-5 bg-canvas rounded-lg border border-border space-y-3">
                <div className="flex gap-3">
                  <div className="flex-1">
                    <label className="font-mono text-xs tracking-label text-text-muted block mb-1">源节点</label>
                    <input
                      value={newEdgeSource}
                      onChange={e => { setNewEdgeSource(e.target.value); handleNodeSearch(e.target.value, setSourceSearch); }}
                      placeholder="搜索节点 ID 或名称..."
                      className="w-full bg-slate text-text-primary px-4 py-2.5 rounded-lg border border-border font-body text-sm focus:outline-none focus:border-brand/60"
                    />
                    {sourceSearch.length > 0 && (
                      <div className="mt-1 bg-slate border border-border rounded-lg overflow-hidden">
                        {sourceSearch.map((n: any) => (
                          <button
                            key={n.id}
                            onClick={() => { setNewEdgeSource(String(n.id)); setSourceSearch([]); }}
                            className="w-full text-left px-4 py-2 text-sm font-body text-text-secondary hover:bg-brand/10 transition-colors"
                          >
                            {n.name} <span className="text-text-muted font-mono text-xs">#{n.id}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="flex-1">
                    <label className="font-mono text-xs tracking-label text-text-muted block mb-1">目标节点</label>
                    <input
                      value={newEdgeTarget}
                      onChange={e => { setNewEdgeTarget(e.target.value); handleNodeSearch(e.target.value, setTargetSearch); }}
                      placeholder="搜索节点 ID 或名称..."
                      className="w-full bg-slate text-text-primary px-4 py-2.5 rounded-lg border border-border font-body text-sm focus:outline-none focus:border-brand/60"
                    />
                    {targetSearch.length > 0 && (
                      <div className="mt-1 bg-slate border border-border rounded-lg overflow-hidden">
                        {targetSearch.map((n: any) => (
                          <button
                            key={n.id}
                            onClick={() => { setNewEdgeTarget(String(n.id)); setTargetSearch([]); }}
                            className="w-full text-left px-4 py-2 text-sm font-body text-text-secondary hover:bg-brand/10 transition-colors"
                          >
                            {n.name} <span className="text-text-muted font-mono text-xs">#{n.id}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div>
                  <label className="font-mono text-xs tracking-label text-text-muted block mb-1">关系类型</label>
                  <input
                    value={newEdgeRelation}
                    onChange={e => setNewEdgeRelation(e.target.value)}
                    placeholder="如: 属于, 包含, 相关..."
                    className="w-full bg-slate text-text-primary px-4 py-2.5 rounded-lg border border-border font-body text-sm focus:outline-none focus:border-brand/60"
                  />
                </div>
                <div className="flex gap-3">
                  <button onClick={() => setShowEdgeCreate(false)} className="flex-1 py-2.5 rounded-lg font-mono text-xs border border-border text-text-muted hover:border-text-muted">
                    取消
                  </button>
                  <button onClick={handleCreateEdge} className="flex-1 bg-brand text-canvas py-2.5 rounded-lg font-mono text-xs hover:bg-brand/90 active:scale-[0.98] transition-all">
                    创建
                  </button>
                </div>
              </div>
            )}

            {/* 边列表 */}
            <div className="flex-1 overflow-y-auto space-y-2 min-h-0">
              {edges.length === 0 ? (
                <div className="text-center py-12 text-text-muted font-body text-sm">暂无关系数据</div>
              ) : (
                edges.map(edge => (
                  <div key={edge.id} className="flex items-center gap-3 p-4 bg-canvas rounded-lg border border-border">
                    <span className="font-mono text-xs text-brand bg-brand/10 px-2 py-1 rounded-md">#{edge.source_id}</span>
                    <span className="text-text-muted font-body text-sm">{edge.source_name || edge.source_id}</span>
                    <span className="text-text-muted font-mono text-xs">→</span>
                    <span className="text-text-muted font-mono text-xs bg-slate px-2 py-1 rounded-md">{edge.relation}</span>
                    <span className="text-text-muted font-mono text-xs">→</span>
                    <span className="text-text-muted font-body text-sm">{edge.target_name || edge.target_id}</span>
                    <span className="font-mono text-xs text-info bg-info/10 px-2 py-1 rounded-md">#{edge.target_id}</span>
                    <div className="flex-1" />
                    <button
                      onClick={() => handleDeleteEdge(edge.id)}
                      className="text-text-muted/50 hover:text-danger transition-colors text-sm"
                    >
                      删除
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
