import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { getConversations, deleteConversation } from '../api/client';
import { useState, useEffect } from 'react';

const NAV_ITEMS: Array<{ path: string; tab: 'chat' | 'import' | 'docs' | 'kg' | 'settings'; label: string; icon: string }> = [
  { path: '/', tab: 'chat', label: '聊天', icon: '💬' },
  { path: '/import', tab: 'import', label: '知识导入', icon: '📥' },
  { path: '/docs', tab: 'docs', label: '文档库', icon: '📚' },
  { path: '/kg', tab: 'kg', label: '知识图谱', icon: '🕸️' },
  { path: '/settings', tab: 'settings', label: '设置', icon: '⚙️' },
];

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { activeTab, setActiveTab, currentConversationId, setCurrentConversationId } = useStore();
  const [convs, setConvs] = useState<any[]>([]);
  const [showConvSidebar, setShowConvSidebar] = useState(true);

  useEffect(() => {
    loadConvs();
  }, []);

  const loadConvs = async () => {
    try {
      const data = await getConversations();
      setConvs(data.conversations || []);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteConv = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('删除此对话？')) return;
    try {
      await deleteConversation(id);
      loadConvs();
      if (currentConversationId === id) {
        setCurrentConversationId(null);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleNav = (path: string, tab: 'chat' | 'import' | 'docs' | 'kg' | 'settings') => {
    setActiveTab(tab);
    navigate(path);
  };

  return (
    <div className="flex h-full bg-canvas">
      {/* 侧边栏 */}
      <nav className="w-64 min-h-screen flex flex-col border-r border-border">
        {/* Logo */}
        <div className="p-8 pb-4">
          <h1 className="font-display text-3xl leading-none">
            <span className="text-text-primary">KG</span>
            <span className="text-brand">.AGENT</span>
          </h1>
        </div>

        {/* Nav Items */}
        <div className="flex-1 flex flex-col gap-1 px-4">
          {NAV_ITEMS.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <button
                key={item.path}
                onClick={() => handleNav(item.path, item.tab)}
                className={`
                  flex items-center gap-3 px-4 py-3.5 rounded-lg
                  text-sm font-body
                  transition-all duration-150 text-left
                  ${isActive
                    ? 'bg-slate text-text-primary border-l-2 border-l-brand'
                    : 'text-text-muted hover:text-text-primary hover:bg-slate/50 border-l-2 border-l-transparent'
                  }
                `}
              >
                <span className="text-base">{item.icon}</span>
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>

        {/* 底部信息 */}
        <div className="p-6 border-t border-border">
          <div className="text-xs font-mono uppercase tracking-label text-text-muted/50">
            知识图谱助手 v2.0
          </div>
        </div>
      </nav>

      {/* 对话历史侧边栏 - 仅在聊天页面显示 */}
      {location.pathname === '/' && (
        <aside className={`${showConvSidebar ? 'w-64' : 'w-0'} min-h-screen border-r border-border transition-all duration-200 overflow-hidden flex-shrink-0`}>
          <div className="w-64 min-h-screen flex flex-col">
            <div className="p-4 border-b border-border flex items-center justify-between">
              <span className="font-mono text-xs uppercase tracking-label text-text-secondary">历史对话</span>
              <button
                onClick={() => setShowConvSidebar(false)}
                className="text-text-muted hover:text-text-primary text-sm"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              {convs.length === 0 ? (
                <div className="p-4 text-center font-mono text-xs text-text-muted/60">
                  暂无对话记录
                </div>
              ) : (
                convs.map((conv) => (
                  <div
                    key={conv.id}
                    onClick={() => {
                      setCurrentConversationId(conv.id);
                      useStore.setState({ messages: conv.messages || [] });
                    }}
                    className={`
                      group relative px-4 py-3 border-b border-border-subtle cursor-pointer
                      hover:bg-slate/50 transition-all
                      ${currentConversationId === conv.id ? 'bg-slate border-l-2 border-l-info' : ''}
                    `}
                  >
                    <div className="font-body text-sm text-text-primary/80 truncate pr-8">
                      {conv.title}
                    </div>
                    <div className="font-mono text-xs text-text-muted mt-1">
                      {conv.updated_at ? new Date(conv.updated_at).toLocaleDateString('zh-CN') : ''}
                    </div>
                    <button
                      onClick={(e) => handleDeleteConv(conv.id, e)}
                      className="absolute right-3 top-3 opacity-0 group-hover:opacity-100 text-text-muted hover:text-danger transition-all text-xs"
                    >
                      🗑
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </aside>
      )}

      {/* 主内容区 */}
      <main className="flex-1 overflow-hidden flex flex-col">
        <Outlet />
      </main>

      {/* 恢复侧边栏按钮 */}
      {location.pathname === '/' && !showConvSidebar && (
        <button
          onClick={() => setShowConvSidebar(true)}
          className="fixed left-64 top-4 z-20 bg-slate text-text-secondary hover:text-text-primary px-3 py-1 rounded-lg border border-border font-mono text-xs"
        >
          ☰ 历史
        </button>
      )}
    </div>
  );
}
