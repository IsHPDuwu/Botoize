import { describe, expect, it } from "vitest";
import { productRoutes, resolveProductRoute, visibleProductRoutes } from "./product-routes";

describe("QQ product route visibility", () => {
  it("keeps unrelated Monoize product routes unavailable", () => {
    for (const id of ["playground", "billing-plans", "models", "wallet", "payments", "groups-legacy"]) {
      const route = productRoutes.find((item) => item.id === id);
      expect(route?.enabled).toBe(false);
      expect(resolveProductRoute(route?.path ?? "", "Owner")).toBeNull();
    }
  });

  it("limits Owner management links to Owner sessions", () => {
    expect(visibleProductRoutes("Admin").some((route) => route.ownerOnly)).toBe(false);
    expect(visibleProductRoutes("Owner").some((route) => route.id === "admin-users")).toBe(true);
    expect(visibleProductRoutes("Owner").some((route) => route.id === "groups")).toBe(true);
    expect(resolveProductRoute("/dashboard/users", "Admin")).toBeNull();
    expect(resolveProductRoute("/dashboard/users", "Owner")?.id).toBe("admin-users");
  });

  it("accepts enabled shared pages for both roles", () => {
    expect(resolveProductRoute("/dashboard/logs", "Admin")?.id).toBe("logs");
    expect(resolveProductRoute("/dashboard/logs", "Owner")?.id).toBe("logs");
  });
});
