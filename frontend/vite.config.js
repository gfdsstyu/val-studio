import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: Vite(5173)가 /api 를 로컬 FastAPI(8000)로 프록시.
// build: dist/ 를 FastAPI 가 정적 서빙 → 단일 localhost 프로세스.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
