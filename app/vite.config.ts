import { defineConfig } from "vite";

// Relative base: the same build works on GitHub Pages (/portolan/) and from a single file.
export default defineConfig({
  base: "./",
  build: { target: "es2020", chunkSizeWarningLimit: 1500 },
});
