import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

export default defineConfig(() => ({
  // Path-safe: build with relative asset URLs so the app can be hosted from any subpath.
  base: "./",
  server: {
    host: true,
    port: 8090,
    /**
     * Local-dev connectivity standard:
     * - Ops UI serves from :8090
     * - Mission Control runs on :8080
     * - Browser talks same-origin to Ops UI; Vite proxies /mission-control/* -> Mission Control
     *
     * Override the proxy target if needed:
     *   MISSION_CONTROL_PROXY_TARGET=http://127.0.0.1:8080 npm run dev
     */
    proxy: {
      "/mission-control": {
        target: process.env.MISSION_CONTROL_PROXY_TARGET || "http://127.0.0.1:8080",
        changeOrigin: true,
        secure: false,
        // /mission-control/ops/status -> /ops/status
        rewrite: (p) => p.replace(/^\/mission-control/, ""),
      },
    },
    fs: {
      // Allow importing the shared ops contract from ../shared
      allow: [path.resolve(__dirname, "..")],
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@ops-contract": path.resolve(__dirname, "../shared/ops-api-contract/src"),
    },
  },
}));

