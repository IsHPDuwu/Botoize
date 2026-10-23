import type { KeyInfo } from './api';

export function keyStatus(key: KeyInfo, grant: { scopes: string[]; revision: number } | undefined, now = Date.now()): string {
  if (key.revoked_at) return '已撤销';
  if (key.expires_at && (!Number.isFinite(Date.parse(key.expires_at)) || Date.parse(key.expires_at) <= now)) return '已过期';
  if (!grant || grant.revision !== key.grant_revision) return '授权已失效';
  if (!key.scopes.every(scope => grant.scopes.includes(scope))) return '权限已收窄';
  return '本地检查有效（以服务端实时鉴权为准）';
}