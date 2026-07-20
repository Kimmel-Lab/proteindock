import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  // Absolute base so the production build works when served under proteindock.com/app/.
  // Override with VITE_BASE_PATH for other deployments (e.g. VITE_BASE_PATH=/ for root).
  base: process.env.VITE_BASE_PATH ?? (mode === "production" ? "/app/" : "/"),
  server: {
    host: "::",
    port: 8080,
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));
