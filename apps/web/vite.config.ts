import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// One app, two builds (docs/ARCHITECTURE.md):
// - live (default): the backend is authoritative; the dev server only proxies REST + WebSocket to it.
// - showcase (`--mode showcase` or VITE_FLY_GOLF_MODE=showcase): the static GitHub Pages site that
//   replays recorded runs from public/showcase/. Pages serves it from
//   https://jameskbb.github.io/fly-golf/, so its base path is /fly-golf/ (FLY_GOLF_BASE overrides
//   it, e.g. for a fork or a custom domain). Live development stays at /.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "../..", "");
  const api = env.VITE_API_URL || "http://127.0.0.1:8000";
  const requested = env.VITE_FLY_GOLF_MODE || (mode === "showcase" ? "showcase" : "live");
  const flyMode = requested === "showcase" ? "showcase" : "live";
  const base = env.FLY_GOLF_BASE || (flyMode === "showcase" ? "/fly-golf/" : "/");
  return {
    base,
    envDir: "../..",
    define: { "import.meta.env.VITE_FLY_GOLF_MODE": JSON.stringify(flyMode) },
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
