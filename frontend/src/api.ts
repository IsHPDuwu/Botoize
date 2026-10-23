export interface SessionUser { id: number; username: string; role: 'Owner' | 'Admin' }
export interface BotInfo { id: number; name: string; app_id: string; is_active: boolean }
export interface KeyInfo { id: number; bot: number; name: string; prefix: string; scopes: string[]; revoked_at: string | null }
let csrfToken = '';
export async function management<T>(path: string, body?: unknown): Promise<T> {
  if (body !== undefined && !csrfToken) {
    const response = await fetch('/api/v1/auth/csrf/', { credentials: 'same-origin' });
    if (!response.ok) throw new Error('无法初始化安全会话');
    const data: unknown = await response.json();
    if (!data || typeof data !== 'object' || !('csrfToken' in data) || typeof data.csrfToken !== 'string' || !data.csrfToken) {
      throw new Error('安全会话返回了无效的 CSRF 令牌');
    }
    csrfToken = data.csrfToken;
  }
  const response = await fetch(`/api/v1/${path}`, {
    credentials: 'same-origin', method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(response.status === 403 ? '请登录或检查操作权限及密码' : `请求失败（${response.status}）`);
  if (response.status === 204) { if (path === 'auth/logout/') csrfToken = ''; return undefined as T; }
  const data = await response.json();
  if (typeof data.csrfToken === 'string') csrfToken = data.csrfToken;
  return data as T;
}

export async function checkBackend(signal?: AbortSignal): Promise<void> {
  const response = await fetch('/health/', { credentials: 'same-origin', signal });
  if (!response.ok) throw new Error('后端健康检查失败');
  const data: unknown = await response.json();
  if (!data || typeof data !== 'object' || !('status' in data) || data.status !== 'ok') {
    throw new Error('后端返回了无效的健康状态');
  }
}