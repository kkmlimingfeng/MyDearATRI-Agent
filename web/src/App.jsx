import { useCallback, useRef, useState } from 'react';
import WorkflowApp from './workflow/WorkflowEditor';
import ChatHome from './chat/ChatHome';
import ParticleTransition from './ParticleTransition';
import { useTheme } from './theme.jsx';

export default function App() {
  useTheme();
  const [page, setPage] = useState('chat');
  const [workflowVisited, setWorkflowVisited] = useState(false);
  const [transition, setTransition] = useState(null);
  const switching = useRef(false);

  const navigate = useCallback((target) => {
    if (target === page || switching.current) return;
    if (target === 'workflow') setWorkflowVisited(true);
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setPage(target);
      return;
    }
    switching.current = true;
    setTransition({ target, id: Date.now() });
  }, [page]);

  return <div className="app-frame">
    <nav className="app-global-nav" aria-label="主页面">
      <button className={page === 'chat' ? 'active' : ''} onClick={() => navigate('chat')} disabled={Boolean(transition)} aria-current={page === 'chat' ? 'page' : undefined}>对话</button>
      <button className={page === 'workflow' ? 'active' : ''} onClick={() => navigate('workflow')} disabled={Boolean(transition)} aria-current={page === 'workflow' ? 'page' : undefined}>工作流</button>
    </nav>
    <div className={`app-page ${page === 'chat' ? 'is-active' : ''}`} aria-hidden={page !== 'chat'} inert={page !== 'chat' ? '' : undefined}>
      <ChatHome onNavigate={navigate} active={page === 'chat'} />
    </div>
    {workflowVisited && <div className={`app-page ${page === 'workflow' ? 'is-active' : ''}`} aria-hidden={page !== 'workflow'} inert={page !== 'workflow' ? '' : undefined}>
      <WorkflowApp />
    </div>}
    {transition && <ParticleTransition key={transition.id} onReveal={() => setPage(transition.target)} onComplete={() => { switching.current = false; setTransition(null); }} />}
  </div>;
}
