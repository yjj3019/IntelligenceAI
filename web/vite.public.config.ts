import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
process.env.VITE_PUBLIC_ONLY = "true";
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist-public" },
});
