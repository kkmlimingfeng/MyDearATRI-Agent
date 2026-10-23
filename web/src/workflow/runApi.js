export async function runWorkflowRequest(payload, onProgress) {
  const endpoint = onProgress ? '/api/run/async' : '/api/run';
  const response = await fetch(endpoint, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  const raw = await response.text();
  let result;
  try { result = raw ? JSON.parse(raw) : {}; }
  catch { throw new Error(`服务返回了无效数据（HTTP ${response.status}）`); }
  if (!response.ok) throw new Error(result.error || 'Agent 运行失败');
  if (!onProgress) return result;
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, 120));
    const statusResponse = await fetch(`/api/run/status?id=${encodeURIComponent(result.job_id)}`, { cache: 'no-store' });
    const status = await statusResponse.json();
    if (!statusResponse.ok) throw new Error(status.error || '读取运行状态失败');
    if (status.done) {
      onProgress(status.events || status.result?.events || [], status.draft || '', null);
      if (status.error) throw new Error(status.error);
      return status.result;
    }
    onProgress(status.events || [], status.draft || '', status.question || null);
  }
}
