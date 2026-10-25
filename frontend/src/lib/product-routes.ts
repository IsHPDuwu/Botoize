export interface ProductRoute {
  id: string;
  path: string;
  title: string;
  description: string;
  icon: string;
  ownerOnly?: boolean;
  enabled: boolean;
}

export const productRoutes: ProductRoute[] = [
  { id: "dashboard", path: "/dashboard", title: "仪表盘", description: "中转平台运行概况", icon: "dashboard", enabled: true },
  { id: "providers", path: "/dashboard/providers", title: "服务提供商", description: "管理 QQ 官方机器人", icon: "bot", enabled: true },
  { id: "tokens", path: "/dashboard/tokens", title: "令牌管理", description: "创建和撤销单 Bot API Key", icon: "key", enabled: true },
  { id: "groups", path: "/dashboard/groups", title: "分组管理", description: "管理 Bot 授权与会话范围", icon: "groups", enabled: true },
  { id: "logs", path: "/dashboard/logs", title: "日志", description: "查看入库事件与投递状态", icon: "logs", enabled: true },
  { id: "subscriptions", path: "/dashboard/subscriptions", title: "订阅端点", description: "配置 HTTPS 事件回调", icon: "subscriptions", enabled: true },
  { id: "admin-users", path: "/dashboard/users", title: "Owner 用户管理", description: "查看控制台用户", icon: "users", ownerOnly: true, enabled: true },
  { id: "settings", path: "/dashboard/admin-settings", title: "接入与系统设置", description: "查看 Webhook、WS 与 OneBot 支持范围", icon: "settings", enabled: true },
  { id: "api-info", path: "/dashboard/api-info", title: "API 接入说明", description: "QQ 官方 API 与代理接入说明", icon: "api-info", enabled: true },
  { id: "playground", path: "/dashboard/playground", title: "Playground", description: "保留源码，暂未启用", icon: "playground", enabled: false },
  { id: "billing-plans", path: "/dashboard/plans", title: "Plans", description: "保留源码，暂未启用", icon: "plans", enabled: false },
  { id: "models", path: "/dashboard/models", title: "Models", description: "保留源码，暂未启用", icon: "models", enabled: false },
  { id: "wallet", path: "/dashboard/wallet", title: "Wallet", description: "保留源码，暂未启用", icon: "wallet", enabled: false },
  { id: "payments", path: "/dashboard/payments", title: "Payments", description: "保留源码，暂未启用", icon: "payments", enabled: false },
  { id: "groups-legacy", path: "/dashboard/monoize-groups", title: "Groups", description: "保留源码，暂未启用", icon: "groups", enabled: false },
];

export function visibleProductRoutes(role: string | undefined) {
  return productRoutes.filter((route) => route.enabled && (!route.ownerOnly || role === "Owner"));
}

export function resolveProductRoute(pathname: string, role: string | undefined): ProductRoute | null {
  const route = productRoutes.find((item) => item.path === pathname);
  if (!route || !route.enabled || (route.ownerOnly && role !== "Owner")) return null;
  return route;
}
