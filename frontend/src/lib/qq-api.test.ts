import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearManagementSession, management, onUnauthorized } from "./qq-api";

const fetchMock = vi.fn<typeof fetch>();
vi.stubGlobal("fetch", fetchMock);

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("management API session handling", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    clearManagementSession();
  });

  it("initializes CSRF before POST and accepts a rotated token", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ csrfToken: "initial" }))
      .mockResolvedValueOnce(jsonResponse({ csrfToken: "rotated", id: 1 }));

    await management("auth/login/", { username: "owner", password: "secret" });
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/auth/csrf/", { credentials: "same-origin" });
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      credentials: "same-origin",
      method: "POST",
      body: JSON.stringify({ username: "owner", password: "secret" }),
    });
    expect(new Headers((fetchMock.mock.calls[1][1] as RequestInit).headers).get("X-CSRFToken")).toBe("initial");

    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 1 }));
    await management("auth/me/");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/auth/me/");
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: "GET", credentials: "same-origin" });
  });

  it("returns undefined for logout 204", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ csrfToken: "initial" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(management("auth/logout/", {})).resolves.toBeUndefined();
  });

  it("notifies subscribers when the session is no longer authenticated", async () => {
    const handler = vi.fn();
    const unsubscribe = onUnauthorized(handler);
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Not authenticated" }, 403));

    await expect(management("auth/me/")).rejects.toMatchObject({ status: 403 });
    expect(handler).toHaveBeenCalledTimes(1);
    unsubscribe();
  });
});
