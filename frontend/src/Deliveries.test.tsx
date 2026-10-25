import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Deliveries } from './Deliveries';
import { management } from './api';
vi.mock('./api', () => ({ management: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('shows actual delivery state rather than claiming business completion', async () => {
  vi.mocked(management).mockResolvedValue({ deliveries: [{ id: 7, bot: 2, event_id: 'event', state: 'delivered', attempts: 1, available_at: null }], has_more: false, next_before: '7' });
  render(<Deliveries />);
  await screen.findByText(/回调已接受/);
  expect(screen.getByText(/不代表业务处理完成/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '更早的投递' })).toBeDisabled();
});