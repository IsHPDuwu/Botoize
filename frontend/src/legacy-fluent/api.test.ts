import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const request = vi.fn();
function response(data: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data };
}
beforeEach(() => { vi.resetModules(); vi.stubGlobal('fetch', request); });
afterEach(() => { vi.unstubAllGlobals(); request.mockReset(); });

describe('management CSRF', () => {
  it('uses the rotated login token and reinitializes after logout', async () => {
    request.mockResolvedValueOnce(response({ csrfToken: 'initial' }))
      .mockResolvedValueOnce(response({ csrfToken: 'rotated', id: 1 }))
      .mockResolvedValueOnce(response(undefined, 204))
      .mockResolvedValueOnce(response({ csrfToken: 'new-session' }))
      .mockResolvedValueOnce(response({ id: 2 }));
    const { management } = await import('./api');
    await management('auth/login/', { username: 'operator', password: 'test' });
    expect(request.mock.calls[1][1]).toMatchObject({ credentials: 'same-origin', headers: { 'X-CSRFToken': 'initial' } });
    await management('auth/logout/', {});
    expect(request.mock.calls[2][1].headers['X-CSRFToken']).toBe('rotated');
    await management('auth/login/', { username: 'other', password: 'test' });
    expect(request.mock.calls[3][0]).toBe('/api/v1/auth/csrf/');
    expect(request.mock.calls[4][1].headers['X-CSRFToken']).toBe('new-session');
  });

  it('does not send sensitive writes after malformed CSRF initialization', async () => {
    request.mockResolvedValue(response({ csrfToken: null }));
    const { management } = await import('./api');
    await expect(management('bots/', { secret: 'never-send' })).rejects.toThrow('无效的 CSRF');
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('preserves the CSRF token after a non-logout 204 response', async () => {
    request.mockResolvedValueOnce(response({ csrfToken: 'session' }))
      .mockResolvedValueOnce(response(undefined, 204))
      .mockResolvedValueOnce(response(undefined, 204));
    const { management } = await import('./api');
    await management('keys/1/revoke/', { password: 'test' });
    await management('keys/2/revoke/', { password: 'test' });
    expect(request).toHaveBeenCalledTimes(3);
    expect(request.mock.calls[2][1].headers['X-CSRFToken']).toBe('session');
  });
});