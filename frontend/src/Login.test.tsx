import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Login } from './Login';
import { management } from './api';
vi.mock('./api', () => ({ management: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('submits credentials and enters the workspace on success', async () => {
  const user = { id: 1, username: 'operator', role: 'Admin' };
  vi.mocked(management).mockResolvedValue(user);
  const onLogin = vi.fn();
  render(<Login onLogin={onLogin} />);
  fireEvent.change(screen.getByLabelText(/^用户名/), { target: { value: 'operator' } });
  fireEvent.change(screen.getByLabelText(/^密码/), { target: { value: 'test-password' } });
  fireEvent.click(screen.getByRole('button', { name: '登录' }));
  await waitFor(() => expect(onLogin).toHaveBeenCalledWith(user));
  expect(management).toHaveBeenCalledWith('auth/login/', { username: 'operator', password: 'test-password' });
});

it('stays on login and clears the password after rejection', async () => {
  vi.mocked(management).mockRejectedValue(new Error('登录失败，请重试'));
  const onLogin = vi.fn();
  render(<Login onLogin={onLogin} />);
  fireEvent.change(screen.getByLabelText(/^用户名/), { target: { value: 'operator' } });
  fireEvent.change(screen.getByLabelText(/^密码/), { target: { value: 'incorrect' } });
  fireEvent.click(screen.getByRole('button', { name: '登录' }));
  await screen.findByText('登录失败，请重试');
  expect(screen.getByLabelText(/^密码/)).toHaveValue('');
  expect(onLogin).not.toHaveBeenCalled();
});