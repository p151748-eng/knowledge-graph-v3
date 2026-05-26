import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { useStore } from '../store/useStore';
import { chatStream } from '../api/client';
import type { EvidenceGrade, PerformanceMetrics, RetrievalRound, SSEEvent, SourceItem } from '../types';

type ChatPath = 'auto' | 'fast' | 'pipeline' | 'paper' | 'self_rag';

const CHAT_PATH_LABELS: Record<ChatPath, string> = {
  auto: '自动',
  fast: '快速',
  pipeline: '标准流程',
  paper: '论文助手',
  self_rag: '自校验检索',
};

const RESPONSE_PATH_LABELS: Record<string, string> = {
  paper_assistant: '论文助手',
  self_rag: '自校验检索',
  fast: '快速',
  pipeline: '标准流程',
};

const CHUNK_TYPE_LABELS: Record<string, string> = {
  abstract: '摘要',
  method: '方法',
  experiment: '实验',
  table: '表格',
  reference: '参考文献',
  related_work: '相关工作',
  conclusion: '结论',
  paragraph: '正文',
  chunk: '分片',
};

const AGENT_LABELS: Record<string, string> = {
  KGRetriever: '知识检索',
  Explainer: '术语解释',
  Integrator: '答案整合',
  FastPath: '快速回答',
};

const PERFORMANCE_LABELS: Record<string, string> = {
  routing: '路由',
  retrieval: '检索',
  grading: '评分',
  repair: '修复',
  context: '上下文',
  generation: '生成',
  sources: '来源',
  total: '总计',
};

function labelForChunkType(type = '') {
  return CHUNK_TYPE_LABELS[type] || type || '分片';
}

function labelForResponsePath(path = '') {
  return RESPONSE_PATH_LABELS[path] || path || '标准流程';
}

function labelForPerformance(key: string) {
  return PERFORMANCE_LABELS[key] || key;
}

export default function ChatPage() {
  const {
    messages, addMessage, clearMessages,
    isProcessing, setIsProcessing,
    agentName, setAgentName,
    stepName, setStepName,
    elapsed, setElapsed,
    sources, setSources,
    explanations, setExplanations,
    metrics, setMetrics,
    currentConversationId, setCurrentConversationId,
  } = useStore();

  const [input, setInput] = useState('');
  const [chatPath, setChatPath] = useState<ChatPath>('auto');
  const chatPathRef = useRef<ChatPath>('auto');
  const convIdRef = useRef<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fullContentRef = useRef('');

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    convIdRef.current = currentConversationId;
  }, [currentConversationId]);

  // ── 发送消息 ──────────────────────────────────────────────────
  const handleSend = useCallback(async (text: string) => {
    if (!text.trim() || isProcessing) return;

    // 取消上一次的请求
    if (abortRef.current) {
      abortRef.current.abort();
    }
    abortRef.current = new AbortController();

    // 添加用户消息
    const userMsg = { role: 'user' as const, content: text.trim() };
    addMessage(userMsg);
    setInput('');
    scrollToBottom();

    // 重置状态
    setIsProcessing(true);
    setAgentName('');
    setStepName('');
    setElapsed(0);
    setSources([]);
    setExplanations([]);
    setMetrics(null);

    // 添加一条空的 AI 消息占位
    addMessage({ role: 'assistant', content: '', sources: [], explanations: [], path: '' });
    fullContentRef.current = '';

    try {
      const stream = await chatStream(text.trim(), convIdRef.current ?? undefined, chatPathRef.current);
      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let partialLine = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        partialLine += decoder.decode(value, { stream: true });
        const lines = partialLine.split('\n');
        partialLine = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.trim() || !line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (raw === '[DONE]') continue;

          try {
            const event: SSEEvent = JSON.parse(raw);
            handleSSEEvent(event);
          } catch {}
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        useStore.getState().updateLastMessage({
          content: (fullContentRef.current || '请求失败，请重试。') + `\n\n[错误] ${(err as Error).message}`,
        });
      }
    } finally {
      setIsProcessing(false);
      setAgentName('');
      setStepName('');
    }
  }, [isProcessing, addMessage, scrollToBottom, setIsProcessing, setAgentName, setStepName, setElapsed, setSources, setExplanations, setMetrics]);

  // ── SSE 事件处理 ───────────────────────────────────────────────
  const handleSSEEvent = (event: SSEEvent) => {
    switch (event.type) {
      case 'status':
        if (event.agent) setAgentName(event.agent);
        if (event.step) setStepName(event.step);
        if (event.elapsed !== undefined) setElapsed(event.elapsed);
        break;

      case 'delta':
        if (event.content !== undefined) {
          fullContentRef.current += event.content;
          useStore.getState().updateLastMessage({ content: fullContentRef.current });
        }
        break;

      case 'sources':
        if (event.data) {
          setSources(event.data);
          useStore.getState().updateLastMessage({ sources: event.data });
        }
        break;

      case 'explanations':
        if (event.data) {
          setExplanations(event.data);
          useStore.getState().updateLastMessage({ explanations: event.data });
        }
        break;

      case 'metrics':
        if (event.conversation_id) {
          setCurrentConversationId(event.conversation_id);
          convIdRef.current = event.conversation_id;
        }
        setMetrics({
          path: event.path,
          processing_time: event.processing_time,
          confidence: event.confidence,
          paper_task: event.paper_task,
          evidence_grade: event.evidence_grade,
          retrieval_rounds: event.retrieval_rounds,
          performance: event.performance,
        });
        useStore.getState().updateLastMessage({
          path: event.path,
          processing_time: event.processing_time,
          confidence: event.confidence,
          paper_task: event.paper_task,
          evidence_grade: event.evidence_grade,
          retrieval_rounds: event.retrieval_rounds,
          performance: event.performance,
        });
        break;

      case 'error':
        fullContentRef.current = (fullContentRef.current || '') + `\n\n[错误] ${event.message}`;
        useStore.getState().updateLastMessage({ content: fullContentRef.current });
        break;

      case 'conversation_id':
        if (event.conversation_id) {
          setCurrentConversationId(event.conversation_id);
          convIdRef.current = event.conversation_id;
        }
        break;
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend(input);
    }
  };

  const examples = [
    '这篇论文主要解决什么问题？',
    '这篇论文的方法部分怎么做的？',
    '实验用了哪些数据集和指标？',
    'A 方法和 B 方法有什么区别？',
    '帮我基于这些论文写相关工作综述。',
    '帮我生成论文大纲。',
  ];

  return (
    <div className="flex flex-col h-full">
      {/* 顶部路径切换 */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-border bg-canvas">
        <span className="text-xs font-mono tracking-label text-text-muted mr-2">回答模式</span>
        {(['auto', 'fast', 'pipeline', 'paper', 'self_rag'] as ChatPath[]).map((p) => (
          <button
            key={p}
            onClick={() => { setChatPath(p); chatPathRef.current = p; }}
            className={`px-3 py-1 rounded-md text-xs font-body transition-all ${
              chatPath === p
                ? 'bg-brand text-canvas'
                : 'bg-slate/50 text-text-muted hover:text-text-secondary hover:bg-slate'
            }`}
          >
            {CHAT_PATH_LABELS[p]}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-2">
          {isProcessing && (
            <StatusIndicator agentName={agentName} stepName={stepName} elapsed={elapsed} />
          )}
        </div>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {messages.map((msg, idx) => (
          <MessageBubble key={idx} msg={msg} isProcessing={isProcessing && idx === messages.length - 1} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区 */}
      <div className="p-6 border-t border-border">
        <div className="flex gap-3 max-w-3xl mx-auto">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend(input);
              }
            }}
            placeholder="问论文概述、方法、实验、对比、综述或写作大纲..."
            disabled={isProcessing}
            rows={1}
            className="flex-1 bg-slate/60 text-text-primary placeholder:text-text-muted/50
                       px-4 py-2.5 rounded-lg border border-border
                       font-body text-sm resize-none
                       focus:outline-none focus:border-brand/60 transition-colors
                       disabled:opacity-40 disabled:cursor-not-allowed
                       min-h-[42px] max-h-[200px]"
            style={{ scrollbarWidth: 'thin' }}
          />
          <button
            onClick={() => handleSend(input)}
            disabled={!input.trim() || isProcessing}
            className="h-[42px] px-6 bg-brand text-canvas rounded-lg font-mono text-xs uppercase tracking-widest
                       hover:bg-brand/90 active:scale-[0.98] transition-all
                       disabled:opacity-30 disabled:cursor-not-allowed disabled:active:scale-100"
          >
            {isProcessing ? '●' : '→'}
          </button>
        </div>
        <div className="flex flex-wrap gap-2 max-w-3xl mx-auto mt-3">
          {examples.map((example) => (
            <button
              key={example}
              onClick={() => { setChatPath('paper'); chatPathRef.current = 'paper'; handleSend(example); }}
              disabled={isProcessing}
              className="px-2.5 py-1 rounded-md bg-slate/50 border border-border text-text-muted hover:text-brand hover:border-brand/40 text-xs transition-colors disabled:opacity-30"
            >
              {example}
            </button>
          ))}
        </div>
        <div className="flex justify-center mt-2">
          <button
            onClick={clearMessages}
            className="text-xs text-text-muted/50 hover:text-text-secondary font-mono transition-colors"
          >
            清空对话
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 消息气泡组件 ─────────────────────────────────────────────────
function MessageBubble({ msg, isProcessing }: { msg: any; isProcessing: boolean }) {
  const isUser = msg.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[75%] ${isUser ? 'order-2' : 'order-1'}`}
      >
        {/* 角色标签 */}
        {!isUser && (
          <div className="text-xs font-mono uppercase tracking-widest text-brand/60 mb-1.5 flex items-center gap-2">
            <span>知识图谱助手</span>
            {msg.path && (
              <span className={`text-xs px-2 py-0.5 rounded-md border ${pathBadgeClass(msg.path)}`}>
                {labelForResponsePath(msg.path)}
              </span>
            )}
          </div>
        )}

        {/* 气泡 */}
        <div
          className={`rounded-lg px-5 py-4 ${
            isUser
              ? 'bg-brand/10 border border-brand/20 rounded-tr-sm'
              : 'bg-slate/60 border border-border-subtle rounded-tl-sm'
          }`}
        >
          {isUser ? (
            <p className="text-text-primary/90 font-body text-sm leading-relaxed whitespace-pre-wrap">
              {msg.content}
            </p>
          ) : (
            <MarkdownContent content={msg.content || ''} isProcessing={isProcessing} />
          )}
        </div>

        {!isUser && (msg.paper_task || msg.evidence_grade || msg.retrieval_rounds?.length || msg.performance) && (
          <PaperInsightPanel msg={msg} />
        )}

        {/* 来源节点 */}
        {!isUser && msg.sources?.length > 0 && (
          <SourceChips sources={msg.sources} />
        )}

        {/* 通俗解释 */}
        {!isUser && msg.explanations?.length > 0 && (
          <div className="mt-3 space-y-2">
            {msg.explanations.map((exp: any, ei: number) => (
              <div key={ei} className="p-3 bg-info/10 rounded-lg border border-info/20">
                <span className="font-mono text-xs uppercase tracking-widest text-info/80 block mb-1">{exp.term}</span>
                <p className="text-text-secondary text-sm font-body">{exp.simple}</p>
                {exp.analogy && (
                  <p className="text-text-muted text-xs italic mt-1">💡 {exp.analogy}</p>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 元数据 */}
        {!isUser && msg.processing_time && (
          <div className="flex items-center gap-3 text-xs font-mono text-text-muted/50 mt-2">
            <span>{msg.processing_time}</span>
            {msg.confidence && <span>置信度 {Math.round(msg.confidence * 100)}%</span>}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 论文洞察面板 ─────────────────────────────────────────────────
function PaperInsightPanel({ msg }: { msg: any }) {
  const task = msg.paper_task || {};
  const grade: EvidenceGrade = msg.evidence_grade || {};
  const rounds: RetrievalRound[] = msg.retrieval_rounds || [];
  const performance: PerformanceMetrics = msg.performance || {};

  return (
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      {task.task_type && (
        <InfoCard title="论文任务">
          <div className="text-text-secondary text-sm">{task.task_type} · {task.expert === 'paper_expert' ? '论文专家' : (task.expert || '论文专家')}</div>
          {task.preferred_chunk_types?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {task.preferred_chunk_types.map((type: string) => <ChunkBadge key={type} type={type} />)}
            </div>
          )}
          {task.reason && <p className="text-text-muted text-xs mt-2">{task.reason}</p>}
        </InfoCard>
      )}
      {(grade.reason || grade.coverage_score !== undefined) && (
        <InfoCard title="证据评分">
          <div className="grid grid-cols-3 gap-2 text-center">
            <Score label="相关" value={grade.relevance_score} />
            <Score label="支撑" value={grade.support_score} />
            <Score label="覆盖" value={grade.coverage_score} />
          </div>
          <div className={`mt-2 text-xs font-mono ${grade.sufficient ? 'text-success' : 'text-warning'}`}>
            {grade.sufficient ? '证据充足' : (grade.next_action || '需要检查')}
          </div>
          {grade.reason && <p className="text-text-muted text-xs mt-1">{grade.reason}</p>}
        </InfoCard>
      )}
      {rounds.length > 0 && (
        <InfoCard title="检索轮次">
          <div className="space-y-2">
            {rounds.map((round, idx) => (
              <div key={idx} className="text-xs text-text-muted border-l border-border pl-2">
                <div className="font-mono text-text-secondary">第 {round.round} 轮 · {round.source}</div>
                <div>关键词 {round.retrieval?.bm25_hits ?? 0} / 向量 {round.retrieval?.semantic_hits ?? 0} / 图谱 {round.retrieval?.graph_hits ?? 0}</div>
                {round.retrieval?.chunk_types?.length ? <div className="text-brand/70">{round.retrieval.chunk_types.map(labelForChunkType).join('、')}</div> : null}
              </div>
            ))}
          </div>
        </InfoCard>
      )}
      {Object.keys(performance).length > 0 && (
        <InfoCard title="性能耗时">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-text-muted">
            {Object.entries(performance).map(([key, value]) => (
              <div key={key} className="flex justify-between gap-3">
                <span className="font-mono">{labelForPerformance(key)}</span>
                <span className="text-text-secondary">{typeof value === 'number' ? `${value.toFixed(2)}s` : '-'}</span>
              </div>
            ))}
          </div>
        </InfoCard>
      )}
    </div>
  );
}

function InfoCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="p-3 rounded-lg bg-canvas/70 border border-border-subtle">
      <div className="font-mono text-xs uppercase tracking-widest text-text-muted mb-2">{title}</div>
      {children}
    </div>
  );
}

function Score({ label, value }: { label: string; value?: number }) {
  const percent = Math.round((value || 0) * 100);
  return (
    <div className="rounded-md bg-slate/50 p-2">
      <div className="font-display text-lg text-text-primary">{percent}%</div>
      <div className="font-mono text-[10px] text-text-muted uppercase">{label}</div>
    </div>
  );
}

function SourceChips({ sources }: { sources: SourceItem[] }) {
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {sources.map((source, index) => (
        <span key={`${source.type}-${source.id}-${index}`} className={`text-xs px-2 py-1 rounded-md border font-mono ${chunkBadgeClass(source.chunk_type || source.type)}`} title={source.section_path || source.description}>
          {source.chunk_type && <span className="mr-1">{labelForChunkType(source.chunk_type)}</span>}
          {source.name}
          {source.section_path && <span className="text-text-muted ml-1">/{source.section_path}</span>}
        </span>
      ))}
    </div>
  );
}

function ChunkBadge({ type }: { type: string }) {
  return <span className={`px-2 py-0.5 rounded-md border text-xs font-mono ${chunkBadgeClass(type)}`}>{labelForChunkType(type)}</span>;
}

function chunkBadgeClass(type = '') {
  const styles: Record<string, string> = {
    abstract: 'bg-brand/10 border-brand/30 text-brand',
    method: 'bg-info/15 border-info/40 text-info',
    experiment: 'bg-warning/10 border-warning/40 text-warning',
    table: 'bg-info/10 border-info/40 text-info',
    reference: 'bg-success/10 border-success/40 text-success',
    related_work: 'bg-danger/10 border-danger/40 text-danger',
    chunk: 'bg-slate/60 border-border text-text-muted',
  };
  return styles[type] || styles.chunk;
}

function pathBadgeClass(path = '') {
  if (path === 'paper_assistant') return 'border-brand/40 text-brand';
  if (path === 'self_rag') return 'border-success/40 text-success';
  if (path === 'fast') return 'border-warning/40 text-warning';
  return 'border-info/40 text-info';
}

// ── Markdown 渲染组件 ────────────────────────────────────────────
function MarkdownContent({ content, isProcessing }: { content: string; isProcessing: boolean }) {
  if (!content && !isProcessing) {
    return <span className="text-text-muted/50 italic text-sm">等待回复...</span>;
  }

  if (!content && isProcessing) {
    return <StreamingCursor />;
  }

  return (
    <div className="markdown-body text-text-primary/90 font-body text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          code({ node, className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || '');
            const isInline = !match && !className;
            return isInline ? (
              <code
                className="bg-slate/80 text-brand px-1.5 py-0.5 rounded font-mono text-xs"
                {...props}
              >
                {children}
              </code>
            ) : (
              <div className="my-3 rounded-lg overflow-hidden border border-border">
                {match && (
                  <div className="px-4 py-1.5 bg-slate/80 border-b border-border text-xs font-mono text-text-muted uppercase tracking-widest">
                    {match[1]}
                  </div>
                )}
                <code className={`block bg-slate/40 px-4 py-3 font-mono text-sm text-text-primary/90 overflow-x-auto ${className || ''}`} {...props}>
                  {children}
                </code>
              </div>
            );
          },
          pre({ children }: any) {
            return <>{children}</>;
          },
          p({ children }: any) {
            return <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>;
          },
          ul({ children }: any) {
            return <ul className="list-disc list-inside space-y-1 mb-3">{children}</ul>;
          },
          ol({ children }: any) {
            return <ol className="list-decimal list-inside space-y-1 mb-3">{children}</ol>;
          },
          li({ children }: any) {
            return <li className="text-text-primary/85">{children}</li>;
          },
          blockquote({ children }: any) {
            return <blockquote className="border-l-3 border-brand/50 pl-4 italic text-text-muted my-3">{children}</blockquote>;
          },
          h1({ children }: any) {
            return <h1 className="text-xl font-display text-text-primary mt-5 mb-3">{children}</h1>;
          },
          h2({ children }: any) {
            return <h2 className="text-lg font-display text-text-primary mt-4 mb-2">{children}</h2>;
          },
          h3({ children }: any) {
            return <h3 className="text-base font-display text-text-primary mt-3 mb-2">{children}</h3>;
          },
          h4({ children }: any) {
            return <h4 className="text-sm font-display text-text-primary mt-3 mb-1">{children}</h4>;
          },
          a({ href, children }: any) {
            return <a href={href} target="_blank" rel="noopener noreferrer" className="text-brand underline underline-offset-2 hover:text-text-primary/80">{children}</a>;
          },
          table({ children }: any) {
            return <div className="overflow-x-auto my-3 rounded-lg border border-border"><table className="w-full border-collapse text-sm">{children}</table></div>;
          },
          thead({ children }: any) {
            return <thead className="bg-slate/60">{children}</thead>;
          },
          th({ children }: any) {
            return <th className="border border-border px-4 py-2 text-left text-text-muted font-mono text-xs uppercase tracking-widest">{children}</th>;
          },
          td({ children }: any) {
            return <td className="border border-border px-4 py-2 text-text-secondary">{children}</td>;
          },
          tr({ children }: any) {
            return <tr className="hover:bg-text-primary/5 transition-colors">{children}</tr>;
          },
          hr() {
            return <hr className="border-border my-5" />;
          },
          strong({ children }: any) {
            return <strong className="text-text-primary font-semibold">{children}</strong>;
          },
          em({ children }: any) {
            return <em className="text-text-muted italic">{children}</em>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
      {isProcessing && <StreamingCursor inline />}
    </div>
  );
}

// ── 流式光标 ────────────────────────────────────────────────────
function StreamingCursor({ inline }: { inline?: boolean }) {
  return (
    <span className={`${inline ? 'inline-block ml-1' : 'block mt-2'}`}>
      <span className="inline-block w-2 h-4 bg-brand animate-pulse ml-1 align-middle rounded-sm" />
    </span>
  );
}

// ── 状态指示器 ──────────────────────────────────────────────────
function StatusIndicator({ agentName, stepName, elapsed }: { agentName: string; stepName: string; elapsed: number }) {
  const colors: Record<string, string> = {
    KGRetriever: '#6db88f',
    Explainer: '#6b8aed',
    Integrator: '#d97757',
    FastPath: '#d4a843',
  };
  const color = colors[agentName] || '#6db88f';

  return (
    <div className="flex items-center gap-3 text-xs font-mono text-text-muted">
      <span className="font-bold" style={{ color }}>{AGENT_LABELS[agentName] || agentName || '处理中'}</span>
      <span>→</span>
      <span className="text-text-secondary">{stepName || '准备中'}</span>
      <span className="ml-2 tabular-nums">{elapsed.toFixed(1)}s</span>
      <div className="w-16 h-1 bg-slate/80 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-300" style={{ width: `${Math.min(100, elapsed * 15)}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}
