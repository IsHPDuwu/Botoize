export type UserRole = "Owner" | "Admin";

export interface SessionUser {
  id: number;
  username: string;
  role: UserRole;
}

export interface BotInfo {
  id: number;
  name: string;
  app_id: string;
  is_active: boolean;
  channel_id: number;
}

export interface UpstreamInterface {
  interface_type: string;
  label: string;
  implemented: boolean;
}

export interface UpstreamChannel {
  id?: number;
  bot_id?: number;
  name: string;
  base_url: string;
  interface_type: string;
  app_id: string;
  is_active: boolean;
  models: ConversationModel[];
}

export interface ConversationModel {
  id?: number;
  name: string;
  isDirect: boolean;
  userid?: string;
  groupid?: string;
}

export interface UpstreamProvider {
  id: number;
  name: string;
  channels: UpstreamChannel[];
}

export interface BotGrant {
  id?: number;
  user_id?: number;
  bot_id?: number;
  bot?: BotInfo;
  scopes: string[];
  is_active?: boolean;
  revision: number;
  all_conversations?: boolean;
  conversations?: number[];
  models?: ConversationModel[];
}

export interface ApiKeyInfo {
  id: number;
  bot: number;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  grant_revision: number;
  all_conversations?: boolean;
  conversations?: number[];
  can_copy?: boolean;
}

export interface HttpSubscription {
  id: number;
  bot: number;
  url: string;
  is_active: boolean;
  is_current: boolean;
  grant_revision: number;
}

export interface EventRecord {
  id: number;
  bot: number;
  event_id: string;
  event_type: string;
  received_at: string;
  payload: unknown;
}

export interface EventPage {
  events: EventRecord[];
  next_before: string | null;
  has_more: boolean;
}

export interface DeliveryRecord {
  id: number;
  event_id: string;
  bot: number;
  user: number;
  state: "pending" | "processing" | "delivered" | "failed" | "cancelled";
  attempts: number;
  available_at: string | null;
  lease_until: string | null;
}

export interface DeliveryPage {
  deliveries: DeliveryRecord[];
  has_more: boolean;
  next_before: string | null;
}

export interface UserSummary {
  id: number;
  username: string;
  role: UserRole;
  is_active: boolean;
}

export interface DashboardOverview {
  window_hours: number;
  window_start: string;
  generated_at: string;
  bot_count: number;
  active_bot_count: number;
  event_count: number;
  delivery_count: number;
  delivered_count: number;
  pending_count: number;
  processing_count: number;
  failed_count: number;
  cancelled_count: number;
}

export class ManagementApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(
    message: string,
    status: number,
    code?: string,
  ) {
    super(message);
    this.name = "ManagementApiError";
    this.status = status;
    this.code = code;
  }
}

const API_BASE = "/api/v1/";
let csrfToken = "";
const unauthorizedHandlers = new Set<() => void>();

export function onUnauthorized(handler: () => void): () => void {
  unauthorizedHandlers.add(handler);
  return () => unauthorizedHandlers.delete(handler);
}

export function clearManagementSession(): void {
  csrfToken = "";
}

async function readCsrfToken(): Promise<string> {
  const response = await fetch(`${API_BASE}auth/csrf/`, { credentials: "same-origin" });
  if (!response.ok) throw new ManagementApiError("无法初始化安全会话", response.status);
  const result: unknown = await response.json();
  if (!result || typeof result !== "object" || !("csrfToken" in result) || typeof result.csrfToken !== "string" || !result.csrfToken) {
    throw new ManagementApiError("安全会话响应无效", response.status);
  }
  csrfToken = result.csrfToken;
  return csrfToken;
}

function errorMessage(body: unknown, status: number): { message: string; code?: string } {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    const detail = record.detail;
    const code = typeof record.code === "string" ? record.code : undefined;
    if (typeof detail === "string") return { message: detail, code };
    if (detail && typeof detail === "object") return { message: JSON.stringify(detail), code };
    return { message: `请求失败（${status}）`, code };
  }
  return { message: `请求失败（${status}）` };
}

export async function management<T>(path: string, body?: unknown, signal?: AbortSignal, method = body === undefined ? "GET" : "POST"): Promise<T> {
  const headers = new Headers();
  if (body !== undefined) {
    if (!csrfToken) await readCsrfToken();
    headers.set("Content-Type", "application/json");
    headers.set("X-CSRFToken", csrfToken);
  }

  const response = await fetch(`${API_BASE}${path.replace(/^\//, "")}`, {
    credentials: "same-origin",
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (response.status === 401) {
    csrfToken = "";
    for (const handler of unauthorizedHandlers) handler();
  }
  if (!response.ok) {
    let parsed: unknown;
    try { parsed = await response.json(); } catch { parsed = null; }
    const error = errorMessage(parsed, response.status);
    if (response.status === 403 && error.message === "Not authenticated") {
      csrfToken = "";
      for (const handler of unauthorizedHandlers) handler();
    }
    throw new ManagementApiError(error.message, response.status, error.code);
  }
  if (response.status === 204) {
    if (path.replace(/^\//, "") === "auth/logout/") csrfToken = "";
    return undefined as T;
  }

  const data: unknown = await response.json();
  if (data && typeof data === "object" && "csrfToken" in data && typeof data.csrfToken === "string") {
    csrfToken = data.csrfToken;
  }
  return data as T;
}

export async function checkBackend(signal?: AbortSignal): Promise<void> {
  const response = await fetch("/health/", { credentials: "same-origin", signal });
  if (!response.ok) throw new ManagementApiError("后端健康检查失败", response.status);
  const body: unknown = await response.json();
  if (!body || typeof body !== "object" || !("status" in body) || body.status !== "ok") {
    throw new ManagementApiError("后端健康状态响应无效", response.status);
  }
}

export const qqApi = {
  me: () => management<SessionUser>("auth/me/"),
  login: (username: string, password: string) => management<SessionUser>("auth/login/", { username, password }),
  logout: () => management<void>("auth/logout/", {}),
  bots: () => management<BotInfo[]>("bots/"),
  grants: () => management<BotGrant[]>("grants/"),
  myGrants: () => management<BotGrant[]>("my-grants/"),
  keys: () => management<ApiKeyInfo[]>("keys/"),
  subscriptions: () => management<HttpSubscription[]>("subscriptions/"),
  events: (before?: string) => management<EventPage>(`events/${before ? `?before=${encodeURIComponent(before)}` : ""}`),
  deliveries: (before?: string) => management<DeliveryPage>(`deliveries/${before ? `?before=${encodeURIComponent(before)}` : ""}`),
  users: () => management<UserSummary[]>("users/"),
  overview: (windowHours: number) => management<DashboardOverview>(`dashboard/overview/?window_hours=${windowHours}`),
};
