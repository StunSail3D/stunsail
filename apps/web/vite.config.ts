import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    // Dev only: forward API calls to a locally running Core (uvicorn on :8000).
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
