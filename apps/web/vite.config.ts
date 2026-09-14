import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The backend is authoritative; the dev server only proxies REST + WebSocket to it.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "../..", "");
  const api = env.VITE_API_URL || "http://127.0.0.1:8000";
  return {
    envDir: "../..",
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": api,
        "/health": api,
        "/ws": { target: api.replace(/^http/, "ws"), ws: true },
      },
    },
    build: { chunkSizeWarningLimit: 1600 },
  };
});
