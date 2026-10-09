import { useState } from 'react';
import WorkflowApp from './workflow/WorkflowEditor';
import ChatHome from './chat/ChatHome';
import { useTheme } from './theme.jsx';

export default function App() {
  useTheme();
  const [page, setPage] = useState('chat');
  return page === 'chat'
    ? <ChatHome onNavigate={setPage} />
    : <WorkflowApp onNavigate={setPage} />;
}
