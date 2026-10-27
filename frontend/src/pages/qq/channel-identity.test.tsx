import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { ChannelIdentity } from './channel-identity'
import { management } from '@/lib/qq-api'

vi.mock('@/lib/qq-api', () => ({ management: vi.fn() }))
const channel = { id:7, name:'Official', app_id:'app', interface_type:'qq_official_websocket', base_url:'https://api.bot.qq.com', is_active:true, models:[] }
beforeEach(() => { vi.clearAllMocks(); Object.defineProperty(navigator, 'clipboard', { configurable:true, value:{writeText:vi.fn().mockResolvedValue(undefined)} }) })

it('fetches first identity through the backend and copies the returned IDs', async () => {
  vi.mocked(management).mockResolvedValue({onebot11:123456,onebot12:'00123456'})
  const refresh=vi.fn().mockResolvedValue(undefined)
  render(<ChannelIdentity channel={channel} canRefresh onRefresh={refresh}/>)
  expect(screen.getAllByText(/待获取/)).toHaveLength(2)
  fireEvent.click(screen.getByRole('button',{name:'获取 / 刷新 ID Official'}))
  await screen.findByText('00123456')
  expect(management).toHaveBeenCalledWith('channels/7/identity/',{})
  expect(refresh).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button',{name:'复制 OB12 ID'}))
  await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('00123456'))
})

it('retains previous IDs after a failed refresh and allows retry', async () => {
  vi.mocked(management).mockRejectedValue(new Error('Unavailable'))
  render(<ChannelIdentity channel={{...channel,connection_ids:{onebot11:12,onebot12:'original'}}} canRefresh onRefresh={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button',{name:'获取 / 刷新 ID Official'}))
  await waitFor(() => expect(screen.getByRole('button',{name:'获取 / 刷新 ID Official'})).toBeEnabled())
  expect(screen.getByText('original')).toBeInTheDocument()
})

it('keeps refresh Owner-only and disables it for stopped Channels', () => {
  const {rerender}=render(<ChannelIdentity channel={channel} canRefresh={false} onRefresh={vi.fn()}/>)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  rerender(<ChannelIdentity channel={{...channel,is_active:false}} canRefresh onRefresh={vi.fn()}/>)
  expect(screen.getByRole('button')).toBeDisabled()
})
