import { useState } from 'react'
import { Link } from 'react-router-dom'
import { BotoizeLogo } from '@/components/BotoizeLogo'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { management } from '@/lib/qq-api'

export function RegisterPage() {
  const [draft,setDraft] = useState({token:'',username:'',password:'',email:''})
  const [busy,setBusy] = useState(false)
  const [message,setMessage] = useState('')
  const [done,setDone] = useState(false)
  async function submit(event: React.FormEvent) {
    event.preventDefault();setBusy(true);setMessage('')
    try {await management('invitations/accept/',draft);setDone(true);setDraft({...draft,token:'',password:''});setMessage('账号已创建，请登录。')}
    catch(error) {setMessage(error instanceof Error ? error.message : '注册失败')}
    finally {setBusy(false)}
  }
  return <div className="flex min-h-dvh items-center justify-center bg-background p-4"><Card className="w-full max-w-md"><CardHeader className="text-center"><BotoizeLogo className="mx-auto mb-3 size-14"/><CardTitle>加入 Botoize</CardTitle><CardDescription>使用 Owner 提供的一次性邀请创建 Admin 账号。</CardDescription></CardHeader><CardContent>{!done && <form onSubmit={event => void submit(event)} className="space-y-4">{(['token','username','email','password'] as const).map(key => <div key={key} className="space-y-2"><Label htmlFor={`register-${key}`}>{{token:'邀请凭证',username:'用户名',email:'邮箱（可选）',password:'密码（至少 12 字符）'}[key]}</Label><Input id={`register-${key}`} required={key !== 'email'} type={key === 'password' || key === 'token' ? 'password' : key === 'email' ? 'email' : 'text'} minLength={key === 'password' ? 12 : undefined} maxLength={key === 'password' || key === 'token' ? 256 : key === 'username' ? 150 : 254} autoComplete={key === 'password' ? 'new-password' : 'off'} value={draft[key]} onChange={event => setDraft({...draft,[key]:event.target.value})}/></div>)}<Button type="submit" className="w-full" disabled={busy}>创建账号</Button></form>}{message && <p role="status" className="mt-3 text-sm">{message}</p>}<Link to="/login" className="mt-4 block text-center text-sm underline">返回登录</Link></CardContent></Card></div>
}
