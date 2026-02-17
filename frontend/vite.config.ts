import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "node:path";

const devApiProxyTarget = process.env.VITE_DEV_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/api": {
        target: devApiProxyTarget,
        changeOrigin: true,
      },
      "/healthz": {
        target: devApiProxyTarget,
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});
