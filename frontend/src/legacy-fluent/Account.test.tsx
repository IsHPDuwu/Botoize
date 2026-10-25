import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Account } from './Account';
import { management } from './api';

vi.mock('./api', () => ({ management: vi.fn() }));
const api = vi.mocked(management);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

function session(role: 'Owner' | 'Admin') {
  api.mockImplementation(async path => {
    if (path === 'auth/me/') return { id: 1, username: 'operator', role };
    if (path === 'bots/' || path === 'keys/' || path === 'grants/' || path === 'my-grants/' || path === 'users/') return [];
    return undefined;
  });
}

describe('management account', () => {
  it('offers only explicitly granted Bots and scopes for Key creation', async () => {
    session('Owner');
    const fallback = api.getMockImplementation()!;
    api.mockImplementation(async (path, body) => {
      if (path === 'bots/') return [{ id: 9, name: 'Not granted', app_id: '9', is_active: true }];
      if (path === 'my-grants/') return [{ bot: { id: 2, name: 'Granted Bot', app_id: '2', is_active: true }, scopes: ['query:read'], revision: 1 }];
      return fallback(path, body);
    });
    render(<Account section="API Key" />);
    await screen.findByText('operator · Owner');
    fireEvent.click(screen.getByRole('combobox', { name: '绑定的 Bot' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Granted Bot' }));
    expect(screen.queryByRole('option', { name: 'Not granted' })).toBeNull();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Key 权限 query:read' }));
    expect(screen.queryByRole('checkbox', { name: 'Key 权限 messages:send' })).toBeNull();
    fireEvent.change(screen.getByLabelText('Key 名称'), { target: { value: 'readonly' } });
    fireEvent.change(screen.getByLabelText('操作确认密码'), { target: { value: 'confirmation' } });
    fireEvent.click(screen.getByRole('button', { name: '创建单 Bot Key' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('keys/', { bot: 2, name: 'readonly', scopes: ['query:read'], password: 'confirmation', expires_at: expect.any(String) }));
  });
  it('creates a Bot with password confirmation and clears sensitive inputs', async () => {
    session('Owner');
    render(<Account />);
    await screen.findByRole('button', { name: '添加 Bot' });
    fireEvent.change(screen.getByLabelText('操作确认密码'), { target: { value: 'confirmation' } });
    fireEvent.change(screen.getByLabelText('Bot 名称'), { target: { value: 'Test Bot' } });
    fireEvent.change(screen.getByLabelText('AppID'), { target: { value: '12345' } });
    fireEvent.change(screen.getByLabelText('AppSecret'), { target: { value: 'test-secret' } });
    fireEvent.click(screen.getByRole('button', { name: '添加 Bot' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('bots/', {
      name: 'Test Bot', app_id: '12345', secret: 'test-secret', password: 'confirmation',
    }));
    await waitFor(() => expect(screen.getByLabelText('操作确认密码')).toHaveValue(''));
    expect(screen.getByLabelText('AppSecret')).toHaveValue('');
  });

  it('does not show Owner operations to an Admin', async () => {
    session('Admin');
    render(<Account />);
    await screen.findByText('operator · Admin');
    expect(screen.queryByRole('button', { name: '添加 Bot' })).toBeNull();
    expect(screen.queryByText('Bot 授权管理')).toBeNull();
    expect(screen.getByRole('button', { name: '创建单 Bot Key' })).toBeDisabled();
  });

  it('disables a grant using its original user, Bot and scopes', async () => {
    session('Owner');
    const fallback = api.getMockImplementation()!;
    api.mockImplementation(async (path, body) => path === 'grants/' && !body
      ? [{ id: 7, user_id: 3, bot_id: 9, scopes: ['events:read'], is_active: true, revision: 2 }]
      : fallback(path, body));
    render(<Account />);
    const disable = await screen.findByRole('button', { name: '停用用户 #3 的 Bot #9 授权' });
    expect(disable).toBeDisabled();
    fireEvent.change(screen.getByLabelText('操作确认密码'), { target: { value: 'confirmation' } });
    fireEvent.click(disable);
    await waitFor(() => expect(api).toHaveBeenCalledWith('grants/', {
      user: 3, bot: 9, scopes: ['events:read'], is_active: false, password: 'confirmation',
    }));
  });
});