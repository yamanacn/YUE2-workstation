import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  build: {
    outDir: "dist/client",
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('/motion') || id.includes('framer-motion')) return 'motion';
            if (id.includes('@radix-ui') || id.includes('react-remove-scroll') || id.includes('@floating-ui')) return 'ui-primitives';
            return 'vendor';
          }
        },
      },
    },
  },
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    proxy: { '/api': { target: 'http://127.0.0.1:8767' } },
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
  },
  preview: { proxy: { '/api': { target: 'http://127.0.0.1:8767' } } },
  plugins: [react()],
});
