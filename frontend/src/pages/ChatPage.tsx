import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { useStore } from '../store/useStore';
import { chatStream, ingestArxiv, routePredict } from '../api/client';
import type { EvidenceGrade, EvidenceItem, ImportPaperAction, PerformanceMetrics, ResearchAction, RetrievalRound, SSEEvent, SourceItem } from '../types';

type ChatPath = 'auto' | 'fast' | 'pipeline' | 'paper' | 'self_rag' | 'research';

interface ExecutionStep {
  agent: string;
  step: string;
  elapsed: number;
  timestamp: number;
}

interface RoutePrediction {
  path: string;
  intent: string;
  confidence: number;
  reason: string;
  features: Record<string, boolean>;
  scores: Record<string, number>;
  path_labels: Record<string, string>;
}

const CHAT_PATH_LABELS: Record<ChatPath, string> = {
  auto: '自动选择',
  fast: '⚡ 快速回答',
  pipeline: '🔄 标准流程',
  paper: '📄 论文助手',
  self_rag: '🔬 自校验检索',
  research: '📋 研究助手',
};

const RESPONSE_PATH_LABELS: Record<string, string> = {
  paper_assistant: '📄 论文助手',
  self_rag: '🔬 自校验检索',
  fast: '⚡ 快速回答',
  pipeline: '🔄 标准流程',
  research: '📋 研究工作流',
};

const PATH_DESCRIPTIONS: Record<string, string> = {
  fast: '适合定义、常识问答和简单解释',
  pipeline: '适合基于知识库的实体关系、概念关联和标准检索回答',
  self_rag: '适合事实查证、结论可靠性验证和需要自我校验的问题',
  paper_assistant: '适合单篇论文精读、方法总结、实验分析和贡献梳理',
  research: '适合文献综述、研究空白、技术路线、开题方案和多论文比较',
};

const CHAT_PATH_HINTS: Record<ChatPath, string> = {
  auto: '自动判断最合适的回答模式',
  fast: '适合定义、常识问答和简单解释',
  pipeline: '适合基于知识库的实体关系、概念关联和标准检索回答',
  paper: '适合单篇论文精读、方法总结、实验分析和贡献梳理',
  self_rag: '适合事实查证、结论可靠性验证和需要自我校验的问题',
  research: '适合文献综述、研究空白、技术路线、开题方案和多论文比较',
};

const AGENT_LABELS: Record<string, string> = {
  RoutePlanner: '🧭 路由判断',
  KGRetriever: '🔍 知识检索',
  Explainer: '📖 术语解释',
  Integrator: '✨ 答案整合',
  FastPath: '⚡ 快速回答',
  SelfRAG: '🔬 自校验检索',
  RetrievalRepair: '🔧 检索修复',
  WebVerifier: '🌐 联网验证',
  PaperExpert: '📄 论文专家',
  PaperAssistant: '📄 论文助手',
  ResearchPlanner: '📋 研究规划',
  ResearchWorkflow: '📋 研究助手',
  CitationVerifier: '✅ 引用验证',
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

function initialAgentForPath(path: string) {
  if (path === 'research') return 'ResearchPlanner';
  if (path === 'paper' || path === 'paper_assistant') return 'PaperAssistant';
  if (path === 'self_rag' || path === 'crag') return 'SelfRAG';
  if (path === 'pipeline') return 'KGRetriever';
  return 'FastPath';
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
    executionSteps, addExecutionStep, clearExecutionSteps,
  } = useStore();

  const [input, setInput] = useState('');
  const [chatPath, setChatPath] = useState<ChatPath>('auto');
  const chatPathRef = useRef<ChatPath>('auto');
  const convIdRef = useRef<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fullContentRef = useRef('');

  // 路由确认弹窗状态
  const [showRouteConfirm, setShowRouteConfirm] = useState(false);
  const [pendingMessage, setPendingMessage] = useState('');
  const [routePrediction, setRoutePrediction] = useState<RoutePrediction | null>(null);
  const [selectedPath, setSelectedPath] = useState<string>('');
  const [predicting, setPredicting] = useState(false);
  const [streamStartedAt, setStreamStartedAt] = useState<number | null>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, executionSteps, scrollToBottom]);

  useEffect(() => {
    convIdRef.current = currentConversationId;
  }, [currentConversationId]);

  useEffect(() => {
    if (!isProcessing || streamStartedAt === null) return;

    const tick = window.setInterval(() => {
      const seconds = (Date.now() - streamStartedAt) / 1000;
      setElapsed(seconds);
      if (!useStore.getState().stepName) {
        setStepName('等待服务端响应...');
      }
    }, 1000);

    return () => window.clearInterval(tick);
  }, [isProcessing, streamStartedAt, setElapsed, setStepName]);

  // ── SSE 事件处理（移到前面，避免闭包问题）──────────────────────────
  const handleSSEEvent = useCallback((event: SSEEvent) => {
    switch (event.type) {
      case 'status':
        if (event.agent) setAgentName(event.agent);
        if (event.step) setStepName(event.step);
        if (event.elapsed !== undefined) setElapsed(event.elapsed);
        // 记录执行步骤到历史
        if (event.agent && event.step) {
          const step: ExecutionStep = {
            agent: event.agent,
            step: event.step,
            elapsed: event.elapsed || 0,
            timestamp: Date.now(),
          };
          addExecutionStep(step);
          const currentSteps = useStore.getState().executionSteps;
          useStore.getState().updateLastMessage({ executionSteps: [...currentSteps, step] });
        }
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
          suggested_actions: event.suggested_actions,
          research_actions: event.research_actions,
          research_intent: event.research_intent,
          answer_verification: event.answer_verification,
          citation_verification: event.citation_verification,
          evidence_items: event.evidence_items,
        });
        useStore.getState().updateLastMessage({
          path: event.path,
          processing_time: event.processing_time,
          confidence: event.confidence,
          paper_task: event.paper_task,
          evidence_grade: event.evidence_grade,
          retrieval_rounds: event.retrieval_rounds,
          performance: event.performance,
          suggested_actions: event.suggested_actions,
          research_actions: event.research_actions,
          research_intent: event.research_intent,
          answer_verification: event.answer_verification,
          citation_verification: event.citation_verification,
          evidence_items: event.evidence_items,
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
  }, [setAgentName, setStepName, setElapsed, addExecutionStep, setSources, setExplanations, setMetrics, setCurrentConversationId]);

  // ── 确认后执行发送（必须先定义，handleSend依赖它）───────────────────────
  const executeSend = useCallback(async (text: string, path: string) => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    abortRef.current = new AbortController();

    const userMsg = { role: 'user' as const, content: text };
    addMessage(userMsg);
    scrollToBottom();

    setIsProcessing(true);
    setAgentName(initialAgentForPath(path));
    setStepName('请求已发送，等待服务端响应...');
    setElapsed(0);
    setSources([]);
    setExplanations([]);
    setMetrics(null);
    clearExecutionSteps();
    setStreamStartedAt(Date.now());

    addMessage({ role: 'assistant', content: '', sources: [], explanations: [], path: '', executionSteps: [] });
    fullContentRef.current = '';

    try {
      const stream = await chatStream(text, convIdRef.current ?? undefined, path);
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
      setStreamStartedAt(null);
    }
  }, [addMessage, scrollToBottom, setIsProcessing, setAgentName, setStepName, setElapsed, setSources, setExplanations, setMetrics, clearExecutionSteps, handleSSEEvent]);

  // ── 发送消息（先预测路由）──────────────────────────────────────────────
  const handleSend = useCallback(async (text: string) => {
    if (!text.trim() || isProcessing) return;

    const trimmedText = text.trim();

    // 如果用户已选择非auto路径，直接执行
    if (chatPathRef.current !== 'auto') {
      executeSend(trimmedText, chatPathRef.current);
      setInput('');
      return;
    }

    // auto模式：先预测路由
    setPredicting(true);
    setIsProcessing(true);
    setAgentName('RoutePlanner');
    setStepName('判断最合适的回答模式...');
    setElapsed(0);
    setPendingMessage(trimmedText);
    setInput('');

    try {
      const prediction = await routePredict(trimmedText, convIdRef.current ?? undefined);
      setRoutePrediction(prediction);
      setSelectedPath(prediction.path);
      setShowRouteConfirm(true);
    } catch (err) {
      // 预测失败，直接用默认路径
      executeSend(trimmedText, 'pipeline');
    } finally {
      setPredicting(false);
      setIsProcessing(false);
      setAgentName('');
      setStepName('');
    }
  }, [isProcessing, executeSend]);

  // ── 确认路由并发送 ──────────────────────────────────────────────────
  const handleConfirmRoute = useCallback(() => {
    setShowRouteConfirm(false);
    executeSend(pendingMessage, selectedPath);
    setPendingMessage('');
    setRoutePrediction(null);
  }, [executeSend, pendingMessage, selectedPath]);

  // ── 取消路由确认 ──────────────────────────────────────────────────────
  const handleCancelRoute = () => {
    setShowRouteConfirm(false);
    setInput(pendingMessage); // 恢复输入
    setPendingMessage('');
    setRoutePrediction(null);
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
      {/* 路由确认弹窗 */}
      {showRouteConfirm && routePrediction && (
        <RouteConfirmModal
          prediction={routePrediction}
          selectedPath={selectedPath}
          onSelectPath={setSelectedPath}
          onConfirm={handleConfirmRoute}
          onCancel={handleCancelRoute}
          pendingMessage={pendingMessage}
        />
      )}

      {/* 顶部路径切换 */}
      <div className="px-6 py-3 border-b border-border bg-canvas">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono tracking-label text-text-muted mr-2">回答模式</span>
          {(['auto', 'fast', 'pipeline', 'paper', 'self_rag', 'research'] as ChatPath[]).map((p) => (
            <button
              key={p}
              onClick={() => { setChatPath(p); chatPathRef.current = p; }}
              title={CHAT_PATH_HINTS[p]}
              className={`px-3 py-1 rounded-md text-xs font-body transition-all ${
                chatPath === p
                  ? 'bg-brand text-canvas'
                  : 'bg-slate/50 text-text-muted hover:text-text-secondary hover:bg-slate'
              }`}
            >
              {CHAT_PATH_LABELS[p]}
            </button>
          ))}
        </div>
        <div className="mt-2 text-xs text-text-muted pl-[4.75rem]">
          {CHAT_PATH_HINTS[chatPath]}
        </div>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {messages.map((msg, idx) => (
          <MessageBubble
            key={idx}
            msg={msg}
            isProcessing={isProcessing && idx === messages.length - 1}
            currentAgent={agentName}
            currentStep={stepName}
            currentElapsed={elapsed}
          />
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
            disabled={isProcessing || predicting}
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
              disabled={isProcessing || predicting}
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
function MessageBubble({ msg, isProcessing, currentAgent, currentStep, currentElapsed }: {
  msg: any;
  isProcessing: boolean;
  currentAgent: string;
  currentStep: string;
  currentElapsed: number;
}) {
  const isUser = msg.role === 'user';
  const steps = msg.executionSteps || [];

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[75%] ${isUser ? 'order-2' : 'order-1'}`}>
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

        {/* 执行进度面板 - 在气泡上方显示 */}
        {!isUser && isProcessing && (
          <ExecutionProgressPanel
            steps={steps}
            currentAgent={currentAgent}
            currentStep={currentStep}
            currentElapsed={currentElapsed}
          />
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

        {!isUser && !isProcessing && (msg.paper_task || msg.evidence_grade || msg.retrieval_rounds?.length || msg.performance || msg.research_actions?.length || msg.evidence_items?.length) && (
          <PaperInsightPanel msg={msg} />
        )}

        {/* 来源节点 */}
        {!isUser && msg.sources?.length > 0 && (
          <SourceChips sources={msg.sources} />
        )}

        {!isUser && msg.suggested_actions?.length > 0 && (
          <ImportActionCards actions={msg.suggested_actions} />
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

// ── 执行进度面板 ─────────────────────────────────────────────────
function ExecutionProgressPanel({ steps, currentAgent, currentStep, currentElapsed }: {
  steps: ExecutionStep[];
  currentAgent: string;
  currentStep: string;
  currentElapsed: number;
}) {
  return (
    <div className="mb-3 p-3 rounded-xl bg-canvas/80 border border-border animate-fade-in">
      {/* 已完成的步骤 */}
      {steps.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {steps.map((step, idx) => (
            <div
              key={idx}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate/50 text-xs font-mono"
            >
              <span className="text-success">✓</span>
              <span className="text-text-secondary">{AGENT_LABELS[step.agent] || step.agent}</span>
              <span className="text-text-muted">{step.elapsed.toFixed(1)}s</span>
            </div>
          ))}
        </div>
      )}

      {/* 当前正在执行的步骤 */}
      {currentAgent ? (
        <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-brand/10 border border-brand/30">
          <div className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full bg-brand animate-pulse" />
            <span className="font-mono text-sm text-brand font-medium">
              {AGENT_LABELS[currentAgent] || currentAgent}
            </span>
          </div>
          <span className="text-text-muted text-xs">→</span>
          <span className="text-text-secondary text-sm font-body">{currentStep || '准备中...'}</span>
          <div className="ml-auto flex items-center gap-2">
            <span className="tabular-nums text-xs font-mono text-text-muted">{currentElapsed.toFixed(1)}s</span>
            <div className="w-24 h-1.5 bg-slate rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-brand transition-all duration-300"
                style={{ width: `${Math.min(100, currentElapsed * 8)}%` }}
              />
            </div>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-slate/40 border border-border-subtle">
          <div className="w-2.5 h-2.5 rounded-full bg-text-muted animate-pulse" />
          <span className="text-text-secondary text-sm font-body">准备中...</span>
        </div>
      )}
    </div>
  );
}

// ── 论文洞察面板 ─────────────────────────────────────────────────
function PaperInsightPanel({ msg }: { msg: any }) {
  const task = msg.paper_task || {};
  const grade: EvidenceGrade = msg.evidence_grade || {};
  const rounds: RetrievalRound[] = msg.retrieval_rounds || [];
  const performance: PerformanceMetrics = msg.performance || {};
  const researchActions: ResearchAction[] = msg.research_actions || [];
  const evidenceItems: EvidenceItem[] = msg.evidence_items || [];

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
      {researchActions.length > 0 && (
        <InfoCard title="研究执行轨迹">
          <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
            {researchActions.map((action, idx) => (
              <div key={`${action.step}-${action.action}-${idx}`} className="text-xs border-l border-border pl-2">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-text-secondary">{action.step}. {action.tool_name || action.action}</span>
                  <span className={action.status === 'completed' ? 'text-success' : action.status === 'failed' ? 'text-danger' : 'text-warning'}>{action.status}</span>
                </div>
                <div className="text-text-muted mt-0.5">{action.action} · {action.node} → {action.next_node || 'done'}</div>
                {action.reason && <div className="text-text-muted mt-0.5">{action.reason}</div>}
                {action.observation_summary && <div className="text-brand/70 mt-0.5">{action.observation_summary}</div>}
              </div>
            ))}
          </div>
        </InfoCard>
      )}
      {evidenceItems.length > 0 && (
        <InfoCard title="原始证据列表">
          <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
            {evidenceItems.map((item, idx) => {
              const metadata = item.metadata || {};
              const url = metadata.url || item.url;
              const origin = labelForEvidenceOrigin(item);
              const supportText = evidenceSupportLabel(item, msg.citation_verification);
              return (
                <div key={`${item.id || item.title || idx}`} className="rounded-md border border-border-subtle bg-slate/30 p-2 text-xs">
                  <div className="flex items-start justify-between gap-3">
                    <div className="font-medium text-text-secondary leading-snug">{item.title || `证据 ${idx + 1}`}</div>
                    <span className="shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-text-muted">{origin}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-text-muted">
                    {metadata.authors && <span>作者：{metadata.authors}</span>}
                    {metadata.year && <span>年份：{metadata.year}</span>}
                    {(metadata.source || metadata.provider) && <span>来源：{[metadata.source, metadata.provider].filter(Boolean).join(' / ')}</span>}
                    {item.score !== undefined && <span>分数：{Number(item.score).toFixed(2)}</span>}
                    <span>支撑：{supportText}</span>
                  </div>
                  {item.content && <p className="mt-1.5 line-clamp-4 text-text-muted leading-relaxed">{item.content}</p>}
                  {url && (
                    <a href={url} target="_blank" rel="noreferrer" className="mt-1.5 block truncate font-mono text-[11px] text-brand hover:underline">
                      {url}
                    </a>
                  )}
                </div>
              );
            })}
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

function labelForEvidenceOrigin(item: EvidenceItem) {
  const sourceType = item.source_type || '';
  const source = item.metadata?.source || '';
  const provider = item.metadata?.provider || '';
  const value = `${sourceType} ${source} ${provider}`.toLowerCase();
  if (value.includes('web') || value.includes('semantic') || value.includes('scholar') || value.includes('ai4scholar')) return '联网';
  if (value.includes('paper')) return '论文库';
  if (value.includes('graph')) return '图谱';
  if (value.includes('knowledge') || value.includes('local')) return '本地';
  return '证据';
}

function evidenceSupportLabel(item: EvidenceItem, verification?: Record<string, any>) {
  const citation = item.citation ? String(item.citation).replace(/[\[\]]/g, '') : '';
  const unsupported = verification?.unsupported_claims || [];
  if (!verification || Object.keys(verification).length === 0) return '未验证';
  if (verification.supported && unsupported.length === 0) return citation ? `已支撑 ${item.citation}` : '已支撑';
  if (verification.supported) return citation ? `部分支撑 ${item.citation}` : '部分支撑';
  return citation ? `待补证 ${item.citation}` : '待补证';
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

function ImportActionCards({ actions }: { actions: ImportPaperAction[] }) {
  const [importingId, setImportingId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, string>>({});

  const handleImport = async (action: ImportPaperAction) => {
    const paperId = action.paper.arxiv_id || action.paper.url;
    setImportingId(paperId);
    setResults((prev) => ({ ...prev, [paperId]: '' }));
    try {
      const result = await ingestArxiv(action.paper.url || paperId, true);
      const chunks = result.chunks_created ?? result.chunks ?? 0;
      const nodes = result.nodes_created ?? 0;
      const edges = result.edges_created ?? 0;
      setResults((prev) => ({ ...prev, [paperId]: `✓ 已入库：文档 ${result.document_id ?? result.doc_id ?? '-'}，分片 ${chunks}，节点 ${nodes}，关系 ${edges}` }));
    } catch (err) {
      setResults((prev) => ({ ...prev, [paperId]: `✗ 入库失败：${(err as Error).message}` }));
    } finally {
      setImportingId(null);
    }
  };

  return (
    <div className="mt-4 space-y-3">
      {actions.filter((action) => action.type === 'import_paper').map((action, idx) => {
        const paperId = action.paper.arxiv_id || action.paper.url;
        const isImported = results[paperId] && results[paperId].startsWith('✓');
        const isFailed = results[paperId] && results[paperId].startsWith('✗');
        return (
          <div
            key={paperId}
            className={`import-action-card p-4 rounded-xl border-2 transition-all duration-300 card-hover-lift ${
              isImported
                ? 'bg-success/10 border-success/40'
                : isFailed
                  ? 'bg-danger/10 border-danger/40'
                  : 'bg-warning/5 border-warning/30 hover:border-warning/50'
            }`}
            style={{ animationDelay: `${idx * 100}ms` }}
          >
            <div className="flex items-start gap-3">
              <div className={`flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center ${
                isImported
                  ? 'bg-success/20'
                  : isFailed
                    ? 'bg-danger/20'
                    : 'bg-warning/20'
              }`}>
                <span className={`text-lg ${isImported ? 'text-success' : isFailed ? 'text-danger' : 'text-warning'}`}>
                  {isImported ? '✓' : isFailed ? '✗' : '📥'}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <div className={`font-mono text-xs uppercase tracking-widest mb-1 ${
                  isImported ? 'text-success' : isFailed ? 'text-danger' : 'text-warning'
                }`}>
                  {isImported ? '已入库' : isFailed ? '入库失败' : '可补充入库论文'}
                </div>
                <div className="text-text-primary text-sm font-medium truncate">{action.paper.title}</div>
                {action.reason && <p className="text-text-muted text-xs mt-1">{action.reason}</p>}
                {action.paper.snippet && (
                  <p className="text-text-secondary text-xs mt-2 line-clamp-2 leading-relaxed">{action.paper.snippet}</p>
                )}
                <div className="flex flex-wrap items-center gap-3 mt-3">
                  <a
                    href={action.paper.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-brand hover:text-brand/80 underline underline-offset-2 transition-colors"
                  >
                    查看原文 →
                  </a>
                  {!isImported && !isFailed && (
                    <button
                      onClick={() => handleImport(action)}
                      disabled={Boolean(importingId)}
                      className={`btn-import px-4 py-1.5 rounded-lg text-xs font-mono transition-all ${
                        importingId === paperId
                          ? 'bg-slate text-text-muted cursor-wait'
                          : 'bg-brand text-canvas hover:bg-brand/90 active:scale-[0.98]'
                      }`}
                    >
                      {importingId === paperId ? '入库中...' : action.label || '下载并解析入库'}
                    </button>
                  )}
                </div>
                {results[paperId] && (
                  <div className={`text-xs mt-2 font-mono ${
                    isImported ? 'text-success' : 'text-danger'
                  }`}>
                    {results[paperId]}
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
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
    return null;
  }

  return (
    <div className="markdown-body text-text-primary/90 font-body text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          code({ className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || '');
            const isInline = !match && !className;
            return isInline ? (
              <code className="bg-slate/80 text-brand px-1.5 py-0.5 rounded font-mono text-xs" {...props}>
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
          pre({ children }: any) { return <>{children}</>; },
          p({ children }: any) { return <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>; },
          ul({ children }: any) { return <ul className="list-disc list-inside space-y-1 mb-3">{children}</ul>; },
          ol({ children }: any) { return <ol className="list-decimal list-inside space-y-1 mb-3">{children}</ol>; },
          li({ children }: any) { return <li className="text-text-primary/85">{children}</li>; },
          blockquote({ children }: any) { return <blockquote className="border-l-3 border-brand/50 pl-4 italic text-text-muted my-3">{children}</blockquote>; },
          h1({ children }: any) { return <h1 className="text-xl font-display text-text-primary mt-5 mb-3">{children}</h1>; },
          h2({ children }: any) { return <h2 className="text-lg font-display text-text-primary mt-4 mb-2">{children}</h2>; },
          h3({ children }: any) { return <h3 className="text-base font-display text-text-primary mt-3 mb-2">{children}</h3>; },
          h4({ children }: any) { return <h4 className="text-sm font-display text-text-primary mt-3 mb-1">{children}</h4>; },
          a({ href, children }: any) { return <a href={href} target="_blank" rel="noopener noreferrer" className="text-brand underline underline-offset-2 hover:text-text-primary/80">{children}</a>; },
          table({ children }: any) { return <div className="overflow-x-auto my-3 rounded-lg border border-border"><table className="w-full border-collapse text-sm">{children}</table></div>; },
          thead({ children }: any) { return <thead className="bg-slate/60">{children}</thead>; },
          th({ children }: any) { return <th className="border border-border px-4 py-2 text-left text-text-muted font-mono text-xs uppercase tracking-widest">{children}</th>; },
          td({ children }: any) { return <td className="border border-border px-4 py-2 text-text-secondary">{children}</td>; },
          tr({ children }: any) { return <tr className="hover:bg-text-primary/5 transition-colors">{children}</tr>; },
          hr() { return <hr className="border-border my-5" />; },
          strong({ children }: any) { return <strong className="text-text-primary font-semibold">{children}</strong>; },
          em({ children }: any) { return <em className="text-text-muted italic">{children}</em>; },
        }}
      >
        {content}
      </ReactMarkdown>
      {isProcessing && <StreamingCursor inline />}
    </div>
  );
}

function StreamingCursor({ inline }: { inline?: boolean }) {
  return (
    <span className={`${inline ? 'inline-block ml-1' : 'block mt-2'}`}>
      <span className="inline-block w-2 h-4 bg-brand animate-pulse ml-1 align-middle rounded-sm" />
    </span>
  );
}

// ── 路由确认弹窗 ──────────────────────────────────────────────────
function RouteConfirmModal({ prediction, selectedPath, onSelectPath, onConfirm, onCancel, pendingMessage }: {
  prediction: RoutePrediction;
  selectedPath: string;
  onSelectPath: (path: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  pendingMessage: string;
}) {
  const paths = ['fast', 'pipeline', 'self_rag', 'paper_assistant', 'research'];

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 animate-fade-in">
      <div className="bg-canvas border border-border rounded-2xl p-6 max-w-lg w-full mx-4 shadow-xl">
        {/* 标题 */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-brand/20 flex items-center justify-center">
            <span className="text-xl">🔀</span>
          </div>
          <div>
            <h3 className="font-display text-lg text-text-primary">确认处理路径</h3>
            <p className="text-xs text-text-muted font-mono">系统将根据问题类型选择合适的处理方式</p>
          </div>
        </div>

        {/* 用户问题预览 */}
        <div className="mb-4 p-3 bg-slate/30 rounded-lg border border-border-subtle">
          <div className="text-xs font-mono text-text-muted mb-1">您的问题</div>
          <div className="text-sm text-text-primary/90 line-clamp-2">{pendingMessage}</div>
        </div>

        {/* 系统推荐 */}
        <div className="mb-4 p-3 bg-brand/10 rounded-lg border border-brand/30">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono text-brand uppercase tracking-widest">系统推荐</span>
            <span className="px-2 py-0.5 rounded bg-brand text-canvas text-xs font-mono">
              置信度 {Math.round(prediction.confidence * 100)}%
            </span>
          </div>
          <div className="text-sm text-text-secondary">{prediction.reason}</div>
        </div>

        {/* 路径选择 */}
        <div className="mb-4">
          <div className="text-xs font-mono text-text-muted mb-2 uppercase tracking-widest">选择处理路径</div>
          <div className="space-y-2">
            {paths.map((path) => (
              <button
                key={path}
                onClick={() => onSelectPath(path)}
                className={`w-full p-3 rounded-lg border transition-all text-left ${
                  selectedPath === path
                    ? 'bg-brand/20 border-brand text-brand'
                    : 'bg-slate/30 border-border-subtle text-text-secondary hover:bg-slate/50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{RESPONSE_PATH_LABELS[path] || path}</span>
                  {selectedPath === path && <span className="text-success">✓</span>}
                </div>
                <div className="text-xs text-text-muted mt-1">{PATH_DESCRIPTIONS[path]}</div>
              </button>
            ))}
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2.5 rounded-lg bg-slate/50 border border-border text-text-secondary font-mono text-sm hover:bg-slate transition-colors"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 px-4 py-2.5 rounded-lg bg-brand text-canvas font-mono text-sm hover:bg-brand/90 transition-colors"
          >
            确认并发送
          </button>
        </div>
      </div>
    </div>
  );
}