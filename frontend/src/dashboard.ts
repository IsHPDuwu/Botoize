export const windows = ['1h', '24h', '7d', '30d'] as const;
export type Window = typeof windows[number];
export const isDemoEnabled = (value: unknown) => value === 'true';
export const successRate = (success: number, failed: number) =>
  success + failed === 0 ? '无数据' : `${(100 * success / (success + failed)).toFixed(1)}%`;

// Independent synthetic source. Never used as an API failure fallback.
export function demoDashboard(window: Window, role: 'Owner' | 'Admin' = 'Owner') {
  const multiplier = { '1h': 1, '24h': 24, '7d': 168, '30d': 720 }[window];
  const end = Date.now();
  const bucketMs = multiplier * 3600000 / 6;
  const buckets = Array.from({ length: 6 }, (_, i) => ({
    id: String(i), label: `${new Date(end - (6 - i) * bucketMs).toISOString()} – ${new Date(end - (5 - i) * bucketMs).toISOString()}`,
    events: (role === 'Owner' ? 80 + i * 17 : 20 + i * 3) * multiplier,
    calls: (role === 'Owner' ? 52 + i * 11 : 12 + i * 2) * multiplier,
  }));
  return {
    buckets, online: role === 'Owner' ? 3 : 1, events: buckets.reduce((n, row) => n + row.events, 0),
    calls: buckets.reduce((n, row) => n + row.calls, 0),
    rate: successRate(990 * multiplier, 10 * multiplier), retry: 4, dead: 1,
    generated: new Date(end).toISOString(),
    start: new Date(end - multiplier * 3600000).toISOString(),
    bucketMinutes: bucketMs / 60000,
  };
}