import { expect, it } from 'vitest';
import { keyStatus } from './keyStatus';
import type { KeyInfo } from './api';
const key: KeyInfo = { id: 1, bot: 1, name: 'test', prefix: 'qqp', scopes: ['query:read'], revoked_at: null, expires_at: null, grant_revision: 1 };
const grant = { scopes: ['query:read'], revision: 1 };
it('distinguishes revoked, expired and invalidated grants', () => {
  expect(keyStatus({ ...key, revoked_at: '2026-01-01' }, grant)).toBe('已撤销');
  expect(keyStatus({ ...key, expires_at: '2026-01-01' }, grant, Date.parse('2026-01-01'))).toBe('已过期');
  expect(keyStatus(key, undefined)).toBe('授权已失效');
  expect(keyStatus(key, { ...grant, revision: 2 })).toBe('授权已失效');
  expect(keyStatus(key, { ...grant, scopes: [] })).toBe('权限已收窄');
  expect(keyStatus(key, grant)).toContain('以服务端实时鉴权为准');
});