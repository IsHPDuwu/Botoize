# QQ 官机真实后端验收

日期：2026-10-25。所有发送经过正在运行的 `http://127.0.0.1:8000` 后端 HTTP API，不是模拟响应或进程内 APIClient。

持久资源：已有 Provider「111」、Bot「依卡」；Provider 7 / Channel 7 / Bot 6 / 会话 10。保留已有配置与授权，只补充批准群会话。
唯一目标：`36407554EC2084AF78BB2ECFC5820ACE`。其他群发送/枚举/探测操作为 0。

## 消息矩阵

| 类型 | QQ 上传 | QQ 发送 | message ID | 幂等重放 |
| --- | --- | --- | --- | --- |
| 文本 msg_type=0 | 不适用 | 200 | 有 | 通过 |
| Markdown msg_type=2 | 不适用 | 200 | 有 | 通过 |
| Markdown + 内嵌键盘 | 不适用 | 200 | 有 | 通过 |
| 引用回复（真实 ref_idx） | 不适用 | 200 | 有 | 通过 |
| 图片 PNG / msg_type=7 | 200 | 200 | 有 | 通过 |
| 视频 MP4 / msg_type=7 | 200 | 200 | 有 | 通过 |
| 语音 WAV / msg_type=7 | 200 | 200 | 有 | 通过 |
| 普通文件 TXT / msg_type=7 | 200 | 200 | 有 | 通过 |

每类向 QQ 实际发送一次；随后同一 Idempotency-Key 与相同正文的 HTTP 调用由后端返回缓存，均带 `Idempotency-Replayed: true`，不是再次向 QQ 发消息。
媒体为合成纯色图片/一秒视频、一秒低音量正弦音频及无隐私测试文本；不使用用户文件。上传均 `srv_send_msg=false`，随后用返回的 opaque file_info 发送。报告不记录 file_info、signed URL、AppID、Secret 或 token。

用户已在本会话明确确认“群里全部收到了”，因此八类消息的群内实际收件也已验证。音视频播放效果、按钮点击回调和未来异步审核变化不因“收到”自动视为全部验收。

ARK、Embed 与流式不在当前群消息接口支持类型列表中，未捏造编号或越界测试频道/私聊。当前群接口只列出 msg_type 0、2、7。

## 其他已通过项

- 通过真实后端进行 Session + CSRF 管理请求，创建临时限权 Key。
- 两次复制同一 token，编辑后 token 不变。
- 无法识别会话目标的接口本地 403；无 media:upload 的 Key 上传本地 403。
- 身份查询 200，事件列表 200；撤销后事件读取 401。
- 测试 Key 撤销，合成管理账号清理；持久 Bot 和批准群保留给用户。
- 标准 HTTPS_PROXY / NO_PROXY 工作；本地管理 HTTP 显式直连。
- Gateway HELLO、READY、心跳 ACK，以及保留数据库 session/sequence 后中断重启的 RESUMED 均真实通过。
- 当前 worker 限定批准群入库，其他目标载荷忽略且不记录。
- 后端完整回归 348 passed，迁移至 0021、模型检查无差异；前端 17 项测试通过。
- 日志页已实查持久 Bot 的 API 调用记录。新增 HTTP 审计保存脱敏操作模板、固定消息类型与幂等重放标记；历史通用路由无法还原。另跑无发送真实 HTTP 检查，身份查询 200、预期权限拒绝和撤销后 401 均出现在列表；没有重新发送一轮群消息。

## 待实际触发/环境支持

- 尚无批准群用户 @Bot 的入站事件，不能宣称事件回流通过；worker 已后台在线等待。
- 交互按钮点击、真实下游 WS 收件与公网回调投递需真实事件及可控接收端；未伪造。
- 未执行真实禁言、踢人、撤回或删除资源。
- PostgreSQL 并发与故障恢复按用户要求暂缓。

## 复现（会真实发消息，勿无意重复执行）

```powershell
uv run --with imageio-ffmpeg python -u manage.py verify_live_backend --owner hpd --all-messages
```

运行于 backend。可选 imageio-ffmpeg 仅用于生成合成 MP4，不加入应用生产依赖。每次执行使用新的测试幂等键，因此再次执行会再发一轮；代码不自动重复失败或未知结果。

官网核对：

- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_files.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html
