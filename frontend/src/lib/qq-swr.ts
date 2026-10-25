import useSWR, { type SWRConfiguration } from "swr";
import { qqApi } from "./qq-api";
import type {
  ApiKeyInfo,
  ApiCallPage,
  BotGrant,
  BotInfo,
  DashboardOverview,
  DeliveryPage,
  EventPage,
  HttpSubscription,
  SessionUser,
  UserSummary,
} from "./qq-api";

const defaults: SWRConfiguration = {
  revalidateOnFocus: true,
  revalidateOnReconnect: true,
  dedupingInterval: 2000,
};

export const QQ_SWR_KEYS = {
  me: "qq/me",
  bots: "qq/bots",
  grants: "qq/grants",
  keys: "qq/keys",
  subscriptions: "qq/subscriptions",
  myGrants: "qq/my-grants",
  users: "qq/users",
  events: "qq/events",
  deliveries: "qq/deliveries",
  apiCalls: "qq/api-calls",
  overview: (windowHours: number) => `qq/overview/${windowHours}`,
} as const;

export function useQQSession(config?: SWRConfiguration) {
  return useSWR<SessionUser>(QQ_SWR_KEYS.me, qqApi.me, { ...defaults, ...config });
}

export function useQQBots(config?: SWRConfiguration) {
  return useSWR<BotInfo[]>(QQ_SWR_KEYS.bots, qqApi.bots, { ...defaults, ...config });
}

export function useQQGrants(config?: SWRConfiguration, enabled = true) {
  return useSWR<BotGrant[]>(enabled ? QQ_SWR_KEYS.grants : null, qqApi.grants, { ...defaults, ...config });
}

export function useQQMyGrants(config?: SWRConfiguration) {
  return useSWR<BotGrant[]>(QQ_SWR_KEYS.myGrants, qqApi.myGrants, { ...defaults, ...config });
}

export function useQQKeys(config?: SWRConfiguration) {
  return useSWR<ApiKeyInfo[]>(QQ_SWR_KEYS.keys, qqApi.keys, { ...defaults, ...config });
}

export function useQQSubscriptions(config?: SWRConfiguration) {
  return useSWR<HttpSubscription[]>(QQ_SWR_KEYS.subscriptions, qqApi.subscriptions, { ...defaults, ...config });
}

export function useQQUsers(config?: SWRConfiguration, enabled = true) {
  return useSWR<UserSummary[]>(enabled ? QQ_SWR_KEYS.users : null, qqApi.users, { ...defaults, ...config });
}

export function useQQEvents(config?: SWRConfiguration, enabled = true) {
  return useSWR<EventPage>(enabled ? QQ_SWR_KEYS.events : null, () => qqApi.events(), { ...defaults, ...config });
}

export function useQQDeliveries(config?: SWRConfiguration, enabled = true) {
  return useSWR<DeliveryPage>(enabled ? QQ_SWR_KEYS.deliveries : null, () => qqApi.deliveries(), { ...defaults, ...config });
}

export function useQQApiCalls(config?: SWRConfiguration, before?: string, enabled = true) {
  return useSWR<ApiCallPage>(enabled ? [QQ_SWR_KEYS.apiCalls, before ?? ""] : null, () => qqApi.apiCalls(before), { ...defaults, ...config });
}

export function useQQOverview(windowHours: number, config?: SWRConfiguration) {
  return useSWR<DashboardOverview>(QQ_SWR_KEYS.overview(windowHours), () => qqApi.overview(windowHours), { ...defaults, ...config });
}
