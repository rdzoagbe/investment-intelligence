import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: process.env.GITHUB_PAGES === "true" ? "/investment-intelligence/" : "/",
  // Local development: forward API calls to the FastAPI server started with uvicorn on port 8000.
  server: { proxy: { "/api": "http://localhost:8000" } },
});
