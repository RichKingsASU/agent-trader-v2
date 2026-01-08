import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

export default defineConfig(() => ({
  // Path-safe: build with relative asset URLs so the app can be hosted from any subpath.
  base: "./",
  server: {
    host: true,
    port: 8090,
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

