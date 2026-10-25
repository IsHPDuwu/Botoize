import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";
import { qqApi, type ApiCallRecord } from "@/lib/qq-api";
import { LogsPage } from "./logs";
import "@/i18n";
import "@testing-library/jest-dom/vitest";

vi.mock("@/lib/qq-api", () => ({ qqApi: { apiCalls: vi.fn(), events: vi.fn(), deliveries: vi.fn() } }));

const call: ApiCallRecord = { id: 45, request_id: "test-trace", bot: 6, api_key: null,
  method: "POST", path: "/qq/v2/groups/{group_id}/messages", message_type: "markdown+keyboard",
  replayed: true, status_code: 200, duration_ms: 123, created_at: "2026-10-25T11:15:30Z" };

function showLogs() {
  return render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0,
    revalidateOnFocus: false, revalidateOnReconnect: false, shouldRetryOnError: false }}><LogsPage /></SWRConfig>);
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(qqApi.apiCalls).mockResolvedValue({ calls: [call], has_more: false, next_before: null });
  vi.mocked(qqApi.events).mockResolvedValue({ events: [], has_more: false, next_before: null });
  vi.mocked(qqApi.deliveries).mockResolvedValue({ deliveries: [], has_more: false, next_before: null });
});

it("shows outbound API calls by default, including safe metadata and replay", async () => {
  showLogs();
  expect(await screen.findByText("test-trace")).toBeInTheDocument();
  expect(screen.getByText(call.path)).toBeInTheDocument();
  expect(screen.getByText("Markdown + 键盘")).toBeInTheDocument();
  expect(screen.getByText("幂等重放（未重复发送）")).toBeInTheDocument();
  expect(screen.getByText("Key 未关联或已删除")).toBeInTheDocument();
  expect(screen.getByText("123 ms")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "更早记录" })).toBeDisabled();
});

it("preserves historical audit rows without inventing their operations", async () => {
  vi.mocked(qqApi.apiCalls).mockResolvedValue({ calls: [{ ...call, path: "^(?:qq|onebot)/(?P<path>.*)$", message_type: "", replayed: null }], has_more: false, next_before: null });
  showLogs();
  expect(await screen.findByText("历史通用路由（操作未记录）")).toBeInTheDocument();
  expect(screen.queryByText("幂等重放（未重复发送）")).not.toBeInTheDocument();
});

it("keeps older API pages on their own cursor and can return to latest", async () => {
  vi.mocked(qqApi.apiCalls).mockImplementation(async (before) => before
    ? { calls: [{ ...call, id: 1, request_id: "older-trace" }], has_more: false, next_before: null }
    : { calls: [call], has_more: true, next_before: "45" });
  showLogs();
  await screen.findByText("test-trace");
  fireEvent.click(screen.getByRole("button", { name: "更早记录" }));
  expect(await screen.findByText("older-trace")).toBeInTheDocument();
  expect(qqApi.apiCalls).toHaveBeenCalledWith("45");
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await waitFor(() => expect(qqApi.apiCalls).toHaveBeenLastCalledWith("45"));
  expect(screen.queryByText("test-trace")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "最新记录" }));
  expect(await screen.findByText("test-trace")).toBeInTheDocument();
});

it("shows inbound event and delivery empty states separately from send calls", async () => {
  showLogs();
  await screen.findByText("test-trace");
  fireEvent.click(screen.getByRole("button", { name: "事件" }));
  expect(await screen.findByText("暂无事件")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "投递" }));
  expect(await screen.findByText("暂无投递记录")).toBeInTheDocument();
});

it("shows load errors without claiming there are no calls", async () => {
  vi.mocked(qqApi.apiCalls).mockRejectedValue(new Error("unavailable"));
  showLogs();
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText("暂无 API 调用")).not.toBeInTheDocument();
});
