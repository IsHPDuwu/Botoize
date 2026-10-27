import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TokensPage } from './tokens'
import { ProviderDialog } from './provider-dialog'
import { ConversationPicker } from './conversation-picker'
import { management } from '@/lib/qq-api'
import { useQQKeys, useQQMyGrants } from '@/lib/qq-swr'
import '@/i18n'
import '@testing-library/jest-dom/vitest'

vi.mock('@/lib/qq-api', () => ({ management: vi.fn() }))
vi.mock('@/lib/qq-swr', () => ({ useQQKeys: vi.fn(), useQQMyGrants: vi.fn() }))

const bot = {id: 1, name: 'Bot A', app_id: 'app', is_active: true, channel_id: 1}
const models = [{id: 10, name: '目标群', isDirect: false, groupid: 'allowed'}]
const grant = {bot, scopes: ['messages:send', 'events:read'], revision: 1,
  all_conversations: false, conversations: [10], models}
const key = {id: 1, bot: 1, name: '测试 Key', prefix: 'qqp_prefix', scopes: ['messages:send'],
  expires_at: null, revoked_at: null, grant_revision: 1, all_conversations: false,
  conversations: [10], can_copy: true}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useQQKeys).mockReturnValue({data: [], isLoading: false, mutate: vi.fn()} as unknown as ReturnType<typeof useQQKeys>)
  vi.mocked(useQQMyGrants).mockReturnValue({data: [grant], isLoading: false, mutate: vi.fn()} as unknown as ReturnType<typeof useQQMyGrants>)
  Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: vi.fn().mockResolvedValue(undefined)}})
})

describe('conversation management UI', () => {
  it('selects only current visible conversations, without future full-access wildcard', () => {
    const change = vi.fn()
    render(<ConversationPicker models={models} all={false} selected={[]} allowAll={false} onChange={change} />)
    expect(screen.queryByText('全部会话（包括未来发现的会话）')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', {name: '全选当前可见会话'}))
    expect(change).toHaveBeenCalledWith(false, [10])
  })

  it('creates a key with explicit scopes and allowed conversation IDs, with no password', async () => {
    vi.mocked(management).mockResolvedValue({...key, token: 'qqp_new'})
    render(<TokensPage />)
    fireEvent.click(screen.getAllByRole('button', {name:'创建令牌'})[0])
    fireEvent.change(screen.getByLabelText('绑定 Bot'), {target:{value:'1'}})
    fireEvent.change(screen.getByLabelText('名称'), {target:{value:'New'}})
    fireEvent.click(screen.getByRole('checkbox', {name:'Full access（当前授权内全部 scope）'}))
    fireEvent.click(screen.getByRole('checkbox', {name:'全选当前可见会话'}))
    fireEvent.click(screen.getByRole('button', {name:'创建 API Key'}))
    await waitFor(() => expect(management).toHaveBeenCalledWith('keys/', expect.objectContaining({bot:1, name:'New', scopes: grant.scopes, all_conversations:false, conversations:[10]}), undefined, 'POST'))
    expect(vi.mocked(management).mock.calls[0][1]).not.toHaveProperty('password')
    expect(await screen.findByText('令牌已创建。')).toBeInTheDocument()
  })

  it('edits without rotating, and copies the same original token', async () => {
    vi.mocked(useQQKeys).mockReturnValue({data: [key], isLoading: false, mutate: vi.fn()} as unknown as ReturnType<typeof useQQKeys>)
    vi.mocked(management).mockResolvedValue({...key, token:'same-token'})
    render(<TokensPage />)
    fireEvent.click(screen.getByRole('button', {name:'复制 测试 Key'}))
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('same-token'))
    fireEvent.click(screen.getByRole('button', {name:'编辑 测试 Key'}))
    expect(screen.getByLabelText('绑定 Bot')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('名称'), {target:{value:'Edited'}})
    fireEvent.click(screen.getByRole('button', {name:'保存配置'}))
    await waitFor(() => expect(management).toHaveBeenCalledWith('keys/1/', expect.objectContaining({name:'Edited', conversations:[10]}), undefined, 'PATCH'))
    expect(vi.mocked(management).mock.calls.some(call => call[0].includes('rotate'))).toBe(false)
  })

  it('explains unrecoverable historical tokens and never reports fake copy success', () => {
    vi.mocked(useQQKeys).mockReturnValue({data: [{...key, can_copy:false}], isLoading: false, mutate: vi.fn()} as unknown as ReturnType<typeof useQQKeys>)
    render(<TokensPage />)
    expect(screen.getByRole('button', {name:'复制 测试 Key'})).toBeDisabled()
    expect(screen.getByText('历史 token 无原文，不能再次复制')).toBeInTheDocument()
    expect(management).not.toHaveBeenCalled()
  })

  it('shows key creation failures without closing the draft dialog', async () => {
    vi.mocked(management).mockRejectedValue(new Error('Conversation selection exceeds your grant'))
    render(<TokensPage />)
    fireEvent.click(screen.getAllByRole('button', {name:'创建令牌'})[0])
    fireEvent.change(screen.getByLabelText('绑定 Bot'), {target:{value:'1'}})
    fireEvent.change(screen.getByLabelText('名称'), {target:{value:'New'}})
    fireEvent.click(screen.getByRole('button', {name:'创建 API Key'}))
    await waitFor(() => expect(management).toHaveBeenCalled())
    expect(await screen.findByText('Conversation selection exceeds your grant')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('provider dialog stores credentials on Channel and Models are conversations', async () => {
    const saved = vi.fn().mockResolvedValue(undefined)
    vi.mocked(management).mockResolvedValue({})
    render(<ProviderDialog current={{id:1,name:'Provider',channels:[{id:1,bot_id:1,name:'Bot A',base_url:'https://api.bot.qq.com',interface_type:'qq_official_websocket',app_id:'app',is_active:true,models}]}} interfaces={[{interface_type:'qq_official_websocket',label:'QQ 官方机器人 WebSocket',implemented:true}]} onClose={vi.fn()} onSaved={saved} />)
    fireEvent.click(screen.getAllByRole('button', {name:'Channels'})[0])
    expect(screen.getByLabelText('AppID')).toHaveValue('app')
    expect(screen.getByLabelText('AppSecret')).toBeInTheDocument()
    expect(screen.queryByLabelText('确认当前密码')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', {name:'添加会话'}))
    const dialog = screen.getByRole('dialog', {name:'添加已知会话'})
    expect(within(dialog).getByLabelText('groupid')).toBeInTheDocument()
    expect(within(dialog).queryByLabelText('AppID')).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', {name:'取消'}))
    await waitFor(() => expect(screen.queryByRole('dialog', {name:'添加已知会话'})).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', {name:'保存'}))
    await waitFor(() => expect(saved).toHaveBeenCalled())
    const body = vi.mocked(management).mock.calls[0][1] as {channels: Record<string, unknown>[]}
    expect(body.channels[0]).toHaveProperty('app_id','app')
    expect(body.channels[0].models).toEqual(models)
  })

  it('saves a new OneBot Channel with a string Bot ID and optional access token', async () => {
    const saved = vi.fn().mockResolvedValue(undefined)
    vi.mocked(management).mockResolvedValue({})
    render(<ProviderDialog current={{id:1,name:'OneBot Provider',channels:[{name:'OneBot 12',base_url:'http://127.0.0.1:3000',interface_type:'onebot_v12',app_id:'self:001',is_active:true,models:[]}]}} interfaces={[{interface_type:'onebot_v12',label:'OneBot 12',implemented:true}]} onClose={vi.fn()} onSaved={saved} />)
    fireEvent.click(screen.getAllByRole('button', {name:'Channels'})[0])
    expect(screen.getByLabelText('Bot ID')).toHaveValue('self:001')
    expect(screen.getByLabelText('Access Token（可选）')).toHaveValue('')
    expect(screen.getByLabelText('HTTP 上报密钥（可选）')).toHaveValue('')
    fireEvent.click(screen.getByRole('button', {name:'保存'}))
    await waitFor(() => expect(saved).toHaveBeenCalled())
    const body = vi.mocked(management).mock.calls[0][1] as {channels: Record<string, unknown>[]}
    expect(body.channels[0]).toMatchObject({interface_type:'onebot_v12', app_id:'self:001', secret:''})
    expect(body.channels[0]).not.toHaveProperty('event_secret')
  })
})
