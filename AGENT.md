前端在 frontend 后端在 backend

后端跑 test 之前先 migrate 数据库

每个小模块完成之后提交一个 commit，但是不要把 commit 作为此次会话的终点，而是应该继续把用户的要求做完再结束会话。

前端不要自己设计，直接照抄 ikaleio/monoize D:\Documents\GitHub\monoize-upstream\frontend 的设计，注意是照抄，不要有任何自己的小巧思

上游资源采用 Provider → Channel → Models 层级：Provider 是服务提供商，每个 Channel 只对应一个 Bot；Models 是该 Bot 下的会话。isDirect=true 使用 userid，false 使用 groupid。后端 Bot 仅作为执行和授权实体，不能再把 Bot 当 Model。

Channel 配置接口类型、base_url、AppID/AppSecret，不保留冗余平台字段；已保存 Channel 可切换 QQ 官方 WebSocket / Webhook。OneBot 上游仅预留，下游适配独立。

会话通过已验签事件发现或历史事件回填；QQ 无法枚举未知群/用户，不伪造同步。Key 权限必须是当前用户授权的子集；全部 HTTP、WS、回调和 replay 统一检查会话。无法识别会话归属的操作对受限凭据拒绝。非登录操作不要求再次输入密码，保留 Session/CSRF/角色/归属校验。

所有添加/编辑流程使用 Monoize 的 Dialog / Provider Channels 工作台布局，复用 frontend/src/pages/providers 下已有源码，不改成页面内联创建表单。

后端 migration 使用 django 生成，不要手写

没干完不要停没干完不要停没干完不要停没干完不要停没干完不要停没干完不要停没干完不要停没干完不要停没干完不要停没干完不要停
