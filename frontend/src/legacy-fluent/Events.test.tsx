import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Events } from './Events';
import { management } from './api';
vi.mock('./api', () => ({ management: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('shows persisted events and pages with the server cursor', async () => {
  vi.mocked(management).mockResolvedValueOnce({ events: [{ id: 5, bot: 1, event_id: 'official-id', event_type: 'C2C_MESSAGE_CREATE', received_at: '2026-10-24T00:00:00Z', payload: { content: '<script>' } }], next_before: '5', has_more: true })
    .mockResolvedValueOnce({ events: [], next_before: null, has_more: false });
  render(<Events />);
  await screen.findByText('事件 ID：official-id');
  expect(screen.getByText(/入库不代表已向下游投递/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '更早的事件' }));
  await screen.findByText('暂无可访问的事件。');
  expect(management).toHaveBeenCalledWith('events/?before=5');
});

it('reports failure and permits retry', async () => {
  vi.mocked(management).mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({ events: [], next_before: null, has_more: false });
  render(<Events />);
  await screen.findByText('事件加载失败，请重试');
  fireEvent.click(screen.getByRole('button', { name: '刷新事件' }));
  await waitFor(() => expect(screen.queryByText('事件加载失败，请重试')).toBeNull());
  await screen.findByText('暂无可访问的事件。');
});