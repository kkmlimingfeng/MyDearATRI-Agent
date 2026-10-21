const ACTIONS = [
  ['read', '读取'],
  ['write', '写入'],
  ['edit', '编辑'],
  ['delete', '删除'],
];

export function permissionsForSandboxMode(mode) {
  if (mode === 'full') {
    return {
      workspace: { read: true, write: true, edit: true, delete: true },
      outside: { read: true, write: true, edit: true, delete: true },
    };
  }
  return {
    workspace: { read: true, write: true, edit: true, delete: true },
    outside: { read: true, write: false, edit: false, delete: false },
  };
}

export function updateSandboxPermission(settings, scope, action, allowed) {
  const permissions = {
    workspace: { ...settings.permissions.workspace },
    outside: { ...settings.permissions.outside },
  };
  permissions[scope][action] = allowed;
  if (scope === 'workspace' && !allowed) permissions.outside[action] = false;
  if (scope === 'outside' && allowed) permissions.workspace[action] = true;
  return { ...settings, permission: 'custom', permissions };
}

export default function SandboxPermissionMatrix({ settings, onChange }) {
  const permissions = settings.permissions;
  return <div className="sandbox-matrix-wrap">
    <table className="sandbox-permission-matrix">
      <thead><tr><th scope="col">操作</th><th scope="col">工作空间内</th><th scope="col">工作空间外</th></tr></thead>
      <tbody>{ACTIONS.map(([action, label]) => <tr key={action}>
        <th scope="row">{label}</th>
        {['workspace', 'outside'].map((scope) => <td key={scope}>
          <input
            type="checkbox"
            checked={permissions[scope][action]}
            disabled={scope === 'outside' && !permissions.workspace[action]}
            aria-label={`${label}：${scope === 'workspace' ? '工作空间内' : '工作空间外'}`}
            onChange={(event) => onChange(scope, action, event.target.checked)}
          />
        </td>)}
      </tr>)}</tbody>
    </table>
    <small>工作空间外不能获得高于工作空间内的权限；写入表示新建，系统运行文件始终可读。</small>
  </div>;
}
