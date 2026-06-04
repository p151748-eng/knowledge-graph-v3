import { create } from 'zustand';

interface ExecutionStep {
  agent: string;
  step: string;
  elapsed: number;
  timestamp: number;
}

interface AppState {
  // UI 状态
  activeTab: 'chat' | 'import' | 'docs' | 'kg' | 'settings';
  setActiveTab: (tab: AppState['activeTab']) => void;

  // 对话状态
  currentConversationId: number | null;
  messages: any[];
  setCurrentConversationId: (id: number | null) => void;
  addMessage: (msg: any) => void;
  updateLastMessage: (updates: any) => void;
  clearMessages: () => void;

  // 执行步骤历史（用于当前消息）
  executionSteps: ExecutionStep[];
  addExecutionStep: (step: ExecutionStep) => void;
  clearExecutionSteps: () => void;

  // 处理状态
  isProcessing: boolean;
  setIsProcessing: (v: boolean) => void;
  agentName: string;
  setAgentName: (v: string) => void;
  stepName: string;
  setStepName: (v: string) => void;
  elapsed: number;
  setElapsed: (v: number) => void;
  sources: any[];
  setSources: (v: any[]) => void;
  explanations: any[];
  setExplanations: (v: any[]) => void;
  metrics: any | null;
  setMetrics: (v: any | null) => void;
}

export const useStore = create<AppState>((set) => ({
  activeTab: 'chat',
  setActiveTab: (tab) => set({ activeTab: tab }),

  currentConversationId: null,
  messages: [],
  setCurrentConversationId: (id) => set({ currentConversationId: id }),
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  updateLastMessage: (updates) => set((state) => {
    const msgs = [...state.messages];
    if (msgs.length > 0) {
      msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...updates };
    }
    return { messages: msgs };
  }),
  clearMessages: () => set({ messages: [], currentConversationId: null, executionSteps: [] }),

  executionSteps: [],
  addExecutionStep: (step) => set((state) => ({ executionSteps: [...state.executionSteps, step] })),
  clearExecutionSteps: () => set({ executionSteps: [] }),

  isProcessing: false,
  setIsProcessing: (v) => set({ isProcessing: v }),
  agentName: '',
  setAgentName: (v) => set({ agentName: v }),
  stepName: '',
  setStepName: (v) => set({ stepName: v }),
  elapsed: 0,
  setElapsed: (v) => set({ elapsed: v }),
  sources: [],
  setSources: (v) => set({ sources: v }),
  explanations: [],
  setExplanations: (v) => set({ explanations: v }),
  metrics: null,
  setMetrics: (v) => set({ metrics: v }),
}));
