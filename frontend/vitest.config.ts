import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react-swc";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: {
    include: ["src/lib/**/*.test.{ts,tsx}", "src/pages/qq/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./src/legacy-fluent/test-setup.ts"],
    testTimeout: 15000,
  },
});