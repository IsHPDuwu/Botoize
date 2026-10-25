import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Subscriptions } from './Subscriptions';
import { management } from './api';
vi.mock('./api', () => ({ management: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('shows explicit grant requirement when no grants exist', async () => {
  vi.mocked(management).mockResolvedValue([]);
  render(<Subscriptions />);
  await screen.findByText(/Owner 也需要显式授权/);
  expect(screen.getByRole('button', { name: '保存订阅' })).toBeDisabled();
});

it('saves a real subscription with password confirmation', async () => {
  vi.mocked(management).mockImplementation(async (path) => path === 'my-grants/' ? [{ bot: { id: 2, name: 'Bot two' }, scopes: ['events:read'], revision: 1 }] : []);
  render(<Subscriptions />);
  await screen.findByRole('combobox', { name: '订阅 Bot' });
  await screen.findByRole('button', { name: '刷新' });
  // Wait for the loading control to become enabled before opening Fluent options.
  const { waitFor } = await import('@testing-library/react');
  await waitFor(() => expect(screen.getByRole('combobox')).not.toBeDisabled());
  fireEvent.click(screen.getByRole('combobox'));
  fireEvent.click(await screen.findByRole('option', { name: 'Bot two' }));
  fireEvent.change(screen.getByLabelText('HTTPS 回调地址'), { target: { value: 'https://example.com/events' } });
  fireEvent.change(screen.getByLabelText('确认当前密码'), { target: { value: 'not-a-real-password' } });
  fireEvent.click(screen.getByRole('button', { name: '保存订阅' }));
  await screen.findByText(/订阅已保存/);
  expect(management).toHaveBeenCalledWith('subscriptions/', { bot: 2, url: 'https://example.com/events', is_active: true, password: 'not-a-real-password' });
  expect(screen.getByLabelText('确认当前密码')).toHaveValue('');
});