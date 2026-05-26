import { useState, useEffect } from 'react';
import { getSettings, updateSettings, getHealth } from '../api/client';
import type { AppSettings, HealthStatus } from '../types';

const PROVIDER_LABELS: Record<string, string> = {
  dashscope: '通义千问 (Qwen)',
  openai: 'OpenAI',
  anthropic: 'Anthropic Claude',
  deepseek: 'DeepSeek',
};

const PROVIDER_MODELS: Record<string, string[]> = {
  dashscope: ['qwen-plus', 'qwen-turbo', 'qwen-max', 'qwen-2.5-72b-instruct', 'qwen-2.5-7b-instruct'],
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
  anthropic: ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229', 'claude-3-haiku-20240307'],
  deepseek: ['deepseek-chat', 'deepseek-coder'],
};

const HEALTH_LABELS: Record<string, string> = {
  connected: '已连接',
  available: '可用',
  degraded: '部分可用',
  disconnected: '未连接',
  unavailable: '不可用',
  error: '异常',
};

function healthLabel(value: unknown) {
  const key = String(value || '');
  return HEALTH_LABELS[key] || key || '未知';
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [provider, setProvider] = useState('dashscope');
  const [model, setModel] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getSettings().then(s => {
      setSettings(s);
      setProvider(s.provider);
      setModel(s.model);
      setTemperature(s.temperature);
    });
    getHealth().then(setHealth);
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateSettings({ provider, model, temperature });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-10">
      {/* 标题 */}
      <div>
        <h1 className="font-display text-3xl text-text-primary">设置</h1>
        <p className="font-mono text-xs tracking-label text-text-muted mt-1">
          配置知识图谱助手系统
        </p>
      </div>

      {/* 健康状态 */}
      <div className="bg-slate rounded-lg p-6 border border-border">
        <div className="font-mono text-xs tracking-label text-text-muted mb-4">系统状态</div>
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: '数据库', key: 'database' },
            { label: 'LLM', key: 'llm' },
            { label: '联网搜索', key: 'web_search' },
            { label: '版本', key: 'version' },
          ].map(item => (
            <div key={item.key} className="text-center p-4 bg-canvas rounded-md border border-border">
              <div className="w-2 h-2 rounded-full mx-auto mb-2"
                   style={{
                     backgroundColor: health?.[item.key as keyof HealthStatus] === 'connected' || health?.[item.key as keyof HealthStatus] === 'available'
                       ? '#6db88f'
                       : health?.[item.key as keyof HealthStatus] === 'degraded'
                       ? '#d4a843'
                       : '#d45d5d',
                   }} />
              <div className="font-mono text-xs tracking-label text-text-muted mb-1">{item.label}</div>
              <div className="font-body text-sm text-text-primary">
                {healthLabel(health?.[item.key as keyof HealthStatus])}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* LLM 配置 */}
      {settings && (
        <div className="bg-slate rounded-lg p-6 border border-border space-y-6">
          <div className="font-mono text-xs tracking-label text-text-muted">LLM 配置</div>

          {/* 提供商 */}
          <div>
            <label className="block font-mono text-xs tracking-label text-text-muted mb-3">
              提供商
            </label>
            <div className="grid grid-cols-2 gap-3">
              {settings.available_providers.map(p => (
                <button
                  key={p}
                  onClick={() => setProvider(p)}
                  className={`
                    py-2.5 px-4 rounded-lg font-mono text-xs tracking-label
                    border transition-all text-left
                    ${provider === p
                      ? 'bg-brand text-canvas border-transparent'
                      : 'bg-canvas text-text-muted border-border hover:border-text-muted'
                    }
                  `}
                >
                  {PROVIDER_LABELS[p] || p}
                </button>
              ))}
            </div>
          </div>

          {/* 模型 */}
          <div>
            <label className="block font-mono text-xs tracking-label text-text-muted mb-1.5">
              模型
            </label>
            <input
              value={model}
              onChange={e => setModel(e.target.value)}
              className="w-full bg-canvas text-text-primary px-4 py-2.5 rounded-lg border border-border
                         font-body text-sm focus:outline-none focus:border-brand/60 transition-colors"
            />
            <div className="mt-2 flex gap-2 flex-wrap">
              {(PROVIDER_MODELS[provider] || []).map(m => (
                <button
                  key={m}
                  onClick={() => setModel(m)}
                  className={`px-2.5 py-1 rounded-md font-mono text-xs border transition-all ${
                    model === m ? 'bg-brand/20 text-brand border-brand/40' : 'text-text-muted border-border hover:border-text-muted'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          {/* 温度 */}
          <div>
            <label className="block font-mono text-xs tracking-label text-text-muted mb-3">
              创造性温度 <span className="text-text-muted/50 ml-2">{temperature}</span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={temperature}
              onChange={e => setTemperature(parseFloat(e.target.value))}
              className="w-full accent-brand"
            />
            <div className="flex justify-between font-mono text-xs text-text-muted mt-1">
              <span>精确</span>
              <span>创造</span>
            </div>
          </div>

          {/* 保存 */}
          <button
            onClick={handleSave}
            disabled={saving}
            className={`w-full py-2.5 rounded-lg font-body text-sm transition-all ${
              saved
                ? 'bg-success text-canvas border border-success/40'
                : 'bg-brand text-canvas hover:bg-brand/90 active:scale-[0.98]'
            } disabled:opacity-40`}
          >
            {saving ? '保存中...' : saved ? '✓ 已保存' : '保存设置'}
          </button>
        </div>
      )}

      {/* Embedding 配置 */}
      {settings && (
        <div className="bg-slate rounded-lg p-6 border border-border">
          <div className="font-mono text-xs tracking-label text-text-muted mb-3">向量模型</div>
          <div className="bg-canvas rounded-md p-4 border border-border">
            <div className="font-mono text-sm text-brand">{settings.embedding_model}</div>
            <div className="text-xs font-body text-text-muted mt-1">用于文档和查询的语义向量编码</div>
          </div>
        </div>
      )}
    </div>
  );
}
