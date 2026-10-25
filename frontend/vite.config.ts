import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_API_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    build: {
      chunkSizeWarningLimit: 1000,
    },
    server: {
      port: 5173,
      strictPort: true,
      allowedHosts: ["localhost", "127.0.0.1", "::1"],
      proxy: {
        "/health": { target: apiTarget, changeOrigin: true },
        "/api": { target: apiTarget, changeOrigin: true },
        "/relay": { target: apiTarget, changeOrigin: true, ws: true },
        "/qq": { target: apiTarget, changeOrigin: true },
        "/onebot": { target: apiTarget, changeOrigin: true, ws: true },
      },
    },
  };
});
