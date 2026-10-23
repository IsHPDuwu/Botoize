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
    if (path === 'bots/' || path === 'keys/') return [];
    return undefined;
  });
}

describe('management account', () => {
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
    expect(screen.getByRole('button', { name: '创建单 Bot Key' })).toBeDisabled();
  });
});