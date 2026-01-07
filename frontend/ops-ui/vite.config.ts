import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

export default defineConfig(() => ({
  // Path-safe: build with relative asset URLs so the app can be hosted from any subpath.
  base: "./",
  server: {
    host: true,
    port: 8090,
  },
  plugins: [react()],
}));

