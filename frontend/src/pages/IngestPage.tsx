import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { ingestArxiv, ingestDocument, ingestFile, webSearch } from '../api/client';

type IngestMode = 'file' | 'text' | 'arxiv' | 'websearch';

const MODE_OPTIONS: Array<{ value: IngestMode; label: string; icon: string }> = [
  { value: 'file', label: '文件上传', icon: '📁' },
  { value: 'text', label: '文本粘贴', icon: '📝' },
  { value: 'arxiv', label: 'arXiv 导入', icon: '📄' },
  { value: 'websearch', label: '联网搜索', icon: '🔍' },
];

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function IngestPage() {
  const [mode, setMode] = useState<IngestMode>('file');
  const [text, setText] = useState('');
  const [title, setTitle] = useState('');
  const [tags, setTags] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchResult, setSearchResult] = useState<any>(null);
  const [arxivInput, setArxivInput] = useState('');
  const [arxivLoading, setArxivLoading] = useState(false);

  // 文件上传状态
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileLoading, setFileLoading] = useState(false);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    const file = acceptedFiles[0];
    if (!file) return;
    setSelectedFile(file);
    setError('');
    setResult(null);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
      'text/html': ['.html', '.htm'],
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'text/csv': ['.csv'],
    },
    multiple: false,
  });

  const handleFileUpload = async () => {
    if (!selectedFile) return;
    setFileLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await ingestFile(selectedFile, tags);
      setResult(res);
      setSelectedFile(null);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '文件导入失败');
    } finally {
      setFileLoading(false);
    }
  };

  const handleIngest = async () => {
    if (!text.trim() || !title.trim()) return;
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const tagList = tags.split(',').map(t => t.trim()).filter(Boolean);
      const res = await ingestDocument(title, text, tagList);
      setResult(res);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '导入失败');
    } finally {
      setLoading(false);
    }
  };

  const handleArxivIngest = async () => {
    if (!arxivInput.trim()) return;
    setArxivLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await ingestArxiv(arxivInput.trim(), true);
      setResult(res);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || 'arXiv 导入失败');
    } finally {
      setArxivLoading(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearchLoading(true);
    setSearchResult(null);

    try {
      const res = await webSearch(searchQuery, true);
      setSearchResult(res);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '搜索失败');
    } finally {
      setSearchLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      {/* 标题 */}
      <div>
        <h1 className="font-display text-3xl text-text-primary">知识导入</h1>
        <p className="font-mono text-xs tracking-label text-text-muted mt-1">
          将论文、文件和网页资料保存到知识库
        </p>
      </div>

      {/* 模式切换标签页 */}
      <div className="flex bg-slate rounded-lg border border-border overflow-hidden">
        {MODE_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => setMode(opt.value)}
            className={`flex-1 px-5 py-2.5 font-body text-sm transition-all text-center ${
              mode === opt.value
                ? 'bg-brand text-canvas'
                : 'text-text-muted hover:text-text-primary hover:bg-slate/80'
            }`}
          >
            {opt.icon} {opt.label}
          </button>
        ))}
      </div>

      {/* ── 文件上传模式 ── */}
      {mode === 'file' && (
        <div className="space-y-5 bg-slate rounded-lg p-6 border border-border">
          {/* 拖拽 / 选择区 */}
          <div
            {...getRootProps()}
            className={`
              border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all
              ${isDragActive ? 'border-brand bg-brand/5' : 'border-border hover:border-brand/50'}
              ${selectedFile ? 'border-brand/30 bg-brand/5' : ''}
            `}
          >
            <input {...getInputProps()} />
            <div className="text-4xl mb-3">{selectedFile ? '✅' : '📁'}</div>
            {selectedFile ? (
              <div>
                <div className="font-body text-text-primary text-sm font-medium">{selectedFile.name}</div>
                <div className="font-mono text-xs text-text-muted mt-1">{formatFileSize(selectedFile.size)}</div>
                <div className="font-mono text-xs text-brand mt-2">点击可重新选择文件</div>
              </div>
            ) : (
              <div>
                <div className="font-mono text-xs tracking-label text-text-muted mb-4">
                  {isDragActive ? '放下文件...' : '拖拽文件到此处，或点击选择文件'}
                </div>
                <div className="inline-block bg-brand text-canvas px-5 py-2.5 rounded-lg font-body text-sm hover:bg-brand/90 transition-all pointer-events-none">
                  选择文件
                </div>
                <div className="font-mono text-[10px] tracking-label text-text-muted/50 mt-3">
                  支持 .pdf / .docx / .xlsx / .csv / .html / .md / .txt
                </div>
              </div>
            )}
          </div>

          {/* 标签 */}
          <div>
            <label className="block font-mono text-xs tracking-label text-text-muted mb-1.5">
              标签（逗号分隔，可选）
            </label>
            <input
              value={tags}
              onChange={e => setTags(e.target.value)}
              placeholder="RAG, LLM, 知识图谱"
              className="w-full bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border
                         font-body text-sm focus:outline-none focus:border-brand/60 transition-colors"
            />
          </div>

          {/* 上传按钮 */}
          <button
            onClick={handleFileUpload}
            disabled={!selectedFile || fileLoading}
            className="w-full bg-brand text-canvas py-2.5 rounded-lg font-body text-sm
                       hover:bg-brand/90 active:scale-[0.98] transition-all disabled:opacity-40"
          >
            {fileLoading ? '上传导入中...' : selectedFile ? `上传并导入 ${selectedFile.name}` : '请先选择文件'}
          </button>
        </div>
      )}

      {/* ── 文本粘贴模式 ── */}
      {mode === 'text' && (
        <div className="space-y-5 bg-slate rounded-lg p-6 border border-border">
          <div>
            <label className="block font-mono text-xs tracking-label text-text-muted mb-1.5">
              文档标题
            </label>
            <input
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="输入文档标题..."
              className="w-full bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border
                         font-body text-sm focus:outline-none focus:border-brand/60 transition-colors"
            />
          </div>

          <div>
            <label className="block font-mono text-xs tracking-label text-text-muted mb-1.5">
              文本内容
            </label>
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder="在此粘贴文本内容..."
              className="w-full bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border
                         font-body text-sm focus:outline-none focus:border-brand/60 transition-colors resize-none
                         min-h-[300px]"
            />
          </div>

          <div>
            <label className="block font-mono text-xs tracking-label text-text-muted mb-1.5">
              标签（逗号分隔，可选）
            </label>
            <input
              value={tags}
              onChange={e => setTags(e.target.value)}
              placeholder="RAG, LLM, 知识图谱"
              className="w-full bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border
                         font-body text-sm focus:outline-none focus:border-brand/60 transition-colors"
            />
          </div>

          <button
            onClick={handleIngest}
            disabled={loading || !text.trim() || !title.trim()}
            className="w-full bg-brand text-canvas py-2.5 rounded-lg font-body text-sm
                       hover:bg-brand/90 active:scale-[0.98] transition-all disabled:opacity-40"
          >
            {loading ? '导入中...' : '导入文档'}
          </button>
        </div>
      )}

      {/* ── arXiv 导入模式 ── */}
      {mode === 'arxiv' && (
        <div className="space-y-5 bg-slate rounded-lg p-6 border border-border">
          <div>
            <label className="block font-mono text-xs tracking-label text-text-muted mb-1.5">
              arXiv ID 或 URL
            </label>
            <div className="flex gap-3">
              <input
                value={arxivInput}
                onChange={e => setArxivInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleArxivIngest()}
                placeholder="例如 1706.03762 或 https://arxiv.org/abs/1706.03762"
                className="flex-1 bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border font-body text-sm focus:outline-none focus:border-brand/60 transition-colors"
              />
              <button
                onClick={handleArxivIngest}
                disabled={arxivLoading || !arxivInput.trim()}
                className="bg-brand text-canvas px-5 py-2.5 rounded-lg font-body text-sm hover:bg-brand/90 active:scale-[0.98] transition-all disabled:opacity-40 whitespace-nowrap"
              >
                {arxivLoading ? '导入中...' : '导入'}
              </button>
            </div>
            <p className="font-mono text-xs tracking-label text-text-muted mt-2">
              导入 arXiv 摘要或 HTML 全文到论文助手
            </p>
          </div>
        </div>
      )}

      {/* ── 联网搜索模式 ── */}
      {mode === 'websearch' && (
        <div className="space-y-5 bg-slate rounded-lg p-6 border border-border">
          <div>
            <label className="block font-mono text-xs tracking-label text-text-muted mb-1.5">
              搜索关键词
            </label>
            <div className="flex gap-3">
              <input
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                placeholder="输入搜索话题..."
                className="flex-1 bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border
                           font-body text-sm focus:outline-none focus:border-brand/60 transition-colors"
              />
              <button
                onClick={handleSearch}
                disabled={searchLoading || !searchQuery.trim()}
                className="bg-brand text-canvas px-5 py-2.5 rounded-lg font-body text-sm
                           hover:bg-brand/90 active:scale-[0.98] transition-all disabled:opacity-40 whitespace-nowrap"
              >
                {searchLoading ? '搜索中...' : '搜索'}
              </button>
            </div>
            <p className="font-mono text-xs tracking-label text-text-muted mt-2">
              联网搜索并将结果保存到知识库
            </p>
          </div>

          {searchResult && (
            <div className="space-y-3 pt-2">
              {searchResult.results?.map((r: any, i: number) => (
                <div key={i} className="bg-canvas rounded-lg p-5 border border-border">
                  <div className="font-body text-text-primary font-medium mb-1">{r.title}</div>
                  <div className="text-text-muted text-sm font-body">{r.snippet}</div>
                  <div className="text-xs font-mono text-brand/60 mt-2 truncate">{r.url}</div>
                </div>
              ))}
              <div className="font-mono text-xs tracking-label text-text-muted p-4 bg-canvas rounded-md border border-border">
                ✓ 已创建 {searchResult.nodes_created} 个节点 · {searchResult.docs_created} 篇文档
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── 通用结果与错误 ── */}
      {result && (
        <div className="p-4 bg-info/20 rounded-lg border border-info/40 space-y-3">
          <div className="font-mono text-xs tracking-label text-info">
            ✓ 导入成功
          </div>
          <div className="grid grid-cols-5 gap-4">
            <div className="text-center p-3 bg-canvas rounded-md">
              <div className="font-display text-2xl text-brand">{result.nodes_created ?? '-'}</div>
              <div className="font-mono text-xs text-text-muted">节点</div>
            </div>
            <div className="text-center p-3 bg-canvas rounded-md">
              <div className="font-display text-2xl text-info">{result.edges_created ?? '-'}</div>
              <div className="font-mono text-xs text-text-muted">关系</div>
            </div>
            <div className="text-center p-3 bg-canvas rounded-md">
              <div className="font-display text-2xl text-text-primary">{result.document_id || result.doc_id || '-'}</div>
              <div className="font-mono text-xs text-text-muted">文档ID</div>
            </div>
            <div className="text-center p-3 bg-canvas rounded-md">
              <div className="font-display text-2xl text-warning">{result.chunks_created ?? result.chunk_count ?? '-'}</div>
              <div className="font-mono text-xs text-text-muted">分片</div>
            </div>
            <div className="text-center p-3 bg-canvas rounded-md">
              <div className="font-display text-sm text-info truncate">{result.source || 'paper'}</div>
              <div className="font-mono text-xs text-text-muted">来源</div>
            </div>
          </div>
          {result.entities_extracted?.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {result.entities_extracted.map((e: any, i: number) => (
                <span key={i} className="px-2.5 py-1 bg-canvas text-text-secondary text-xs rounded-md border border-border">
                  {e.name}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="p-4 bg-danger/20 rounded-lg border border-danger/40 text-danger text-sm">
          {error}
        </div>
      )}
    </div>
  );
}
