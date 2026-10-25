import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";
import { qqApi, type ApiCallRecord } from "@/lib/qq-api";
import { LogsPage } from "./logs";
import "@/i18n";
import "@testing-library/jest-dom/vitest";

vi.mock("@/lib/qq-api", () => ({ qqApi: { apiCalls: vi.fn(), events: vi.fn(), deliveries: vi.fn() } }));

const call: ApiCallRecord = { id: 45, request_id: "test-trace", bot: 6, api_key: null,
  bot_name: "依卡", username: "hpd", key_name: "",
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
  Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: vi.fn().mockResolvedValue(undefined)}});
});

it("shows outbound API calls by default, including safe metadata and replay", async () => {
  showLogs();
  expect(await screen.findByText("test-t")).toBeInTheDocument();
  expect(screen.getByText(call.path)).toBeInTheDocument();
  expect(screen.getByText("Markdown + 键盘")).toBeInTheDocument();
  expect(screen.getByText("幂等重放（未重复发送）")).toBeInTheDocument();
  expect(screen.getByText("Key 未关联或已删除")).toBeInTheDocument();
  expect(screen.getByText("123 ms")).toBeInTheDocument();
  expect(screen.getByText("依卡")).toBeInTheDocument();
  expect(screen.getByText("hpd")).toBeInTheDocument();
  expect(screen.queryByText("点击复制")).not.toBeInTheDocument();
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
  await screen.findByText("test-t");
  fireEvent.click(screen.getByRole("button", { name: "更早记录" }));
  expect(await screen.findByText("older-")).toBeInTheDocument();
  expect(qqApi.apiCalls).toHaveBeenCalledWith("45");
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await waitFor(() => expect(qqApi.apiCalls).toHaveBeenLastCalledWith("45"));
  expect(screen.queryByText("test-t")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "最新记录" }));
  expect(await screen.findByText("test-t")).toBeInTheDocument();
});

it("shows inbound event and delivery empty states separately from send calls", async () => {
  showLogs();
  await screen.findByText("test-t");
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

it("copies the full request ID from the six-character button", async () => {
  showLogs();
  const button = await screen.findByRole('button', {name: '复制 Request ID test-t'});
  expect(button).toHaveTextContent('test-t');
  fireEvent.click(button);
  await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('test-trace'));
});

it("applies filters on the server and resets the older-page cursor", async () => {
  vi.mocked(qqApi.apiCalls).mockResolvedValue({calls: [call], has_more: true, next_before: '45'});
  showLogs();
  await screen.findByText('test-t');
  fireEvent.click(screen.getByRole('button', {name: '更早记录'}));
  await waitFor(() => expect(qqApi.apiCalls).toHaveBeenCalledWith('45'));
  fireEvent.change(screen.getByLabelText('搜索日志'), {target: {value: '依卡'}});
  fireEvent.change(screen.getByLabelText('操作用户', {selector: 'input'}), {target: {value: 'hpd'}});
  fireEvent.click(screen.getByRole('button', {name: '应用筛选'}));
  await waitFor(() => expect(qqApi.apiCalls).toHaveBeenLastCalledWith(undefined, {search: '依卡', username: 'hpd'}));
  expect(screen.queryByRole('button', {name: '最新记录'})).not.toBeInTheDocument();
});
