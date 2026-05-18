import type { ServerResponse } from "http";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        configure(proxy) {
          proxy.on("error", (_err, _req, res) => {
            const r = res as ServerResponse | undefined;
            if (r && !r.headersSent) {
              r.writeHead(503, { "Content-Type": "application/json; charset=utf-8" });
              r.end(
                JSON.stringify({
                  detail:
                    "Cannot reach the Python API on http://127.0.0.1:8000. " +
                    "In another terminal run: cd frontend/server && uvicorn app:app --reload --host 127.0.0.1 --port 8000",
                }),
              );
            }
          });
        },
      },
    },
  },
});
