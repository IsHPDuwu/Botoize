import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { ChannelConnection } from './channel-connection'
import { management, type ChannelStatus } from '@/lib/qq-api'

vi.mock('@/lib/qq-api', () => ({management:vi.fn()}))
const channel={id:7,name:'Primary',base_url:'https://api.bot.qq.com',app_id:'app',interface_type:'qq_official_websocket',is_active:true,models:[]}
const connected:ChannelStatus={bot:6,channel:7,name:'Primary',channel_name:'Primary',provider_name:'Provider',interface_type:channel.interface_type,enabled:true,worker_lease_live:true,session_recorded:true,upstream_connected:true,connection_state:'connected',lease_until:null,last_call_at:null,last_http_status:null}
beforeEach(() => { vi.clearAllMocks() })

it('shows established upstream connection, queues a manual reconnect and refreshes status', async () => {
  vi.mocked(management).mockResolvedValue({state:'queued'})
  const refresh=vi.fn().mockResolvedValue(undefined)
  const {rerender}=render(<ChannelConnection channel={channel} status={connected} failed={false} canReconnect onRefresh={refresh}/>)
  expect(screen.getByText('已连接')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'重新连接 Primary'}))
  await waitFor(() => expect(management).toHaveBeenCalledWith('channels/7/reconnect/',{}))
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce())
  expect(screen.getByText('等待重连')).toBeInTheDocument()
  expect(screen.getByRole('button')).toBeDisabled()
  rerender(<ChannelConnection channel={channel} status={{...connected,reconnect_requested_at:'2026-10-27T10:00:00Z',reconnect_processed_at:'2026-10-27T10:00:01Z'}} failed={false} canReconnect onRefresh={refresh}/>)
  expect(screen.getByText('已连接')).toBeInTheDocument()
  expect(screen.getByRole('button')).toBeEnabled()
})

it('keeps a failed reconnect actionable and never claims success', async () => {
  vi.mocked(management).mockRejectedValue(new Error('Request denied'))
  render(<ChannelConnection channel={channel} status={{...connected,connection_state:'disconnected',upstream_connected:false}} failed={false} canReconnect onRefresh={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button'))
  await waitFor(() => expect(screen.getByRole('button')).toBeEnabled())
  expect(screen.getByText('未连接')).toBeInTheDocument()
  expect(screen.queryByText('等待重连')).not.toBeInTheDocument()
})

it('distinguishes webhook checks and keeps operator controls Owner-only', () => {
  const {rerender}=render(<ChannelConnection channel={{...channel,interface_type:'qq_official_webhook'}} status={{...connected,connection_state:'webhook',last_check_at:'2026-10-27T10:00:00Z',last_check_ok:true}} failed={false} canReconnect onRefresh={vi.fn()}/>)
  expect(screen.getByRole('button',{name:'检查上游 Primary'})).toBeEnabled()
  expect(screen.getByText('Webhook 接收')).toBeInTheDocument()
  expect(screen.getByText(/最近 HTTP 检查成功/)).toBeInTheDocument()
  rerender(<ChannelConnection channel={channel} status={connected} failed={false} canReconnect={false} onRefresh={vi.fn()}/>)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('shows unavailable status after polling errors and disables stopped Channels', () => {
  const {rerender}=render(<ChannelConnection channel={channel} status={connected} failed canReconnect onRefresh={vi.fn()}/>)
  expect(screen.getByText('状态读取失败')).toBeInTheDocument()
  expect(screen.queryByText('已连接')).not.toBeInTheDocument()
  rerender(<ChannelConnection channel={{...channel,is_active:false}} status={connected} failed={false} canReconnect onRefresh={vi.fn()}/>)
  expect(screen.getByText('已停用')).toBeInTheDocument()
  expect(screen.getByRole('button')).toBeDisabled()
})
