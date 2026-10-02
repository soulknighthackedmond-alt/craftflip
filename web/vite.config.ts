import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API and the SPA ship as one process, so the dev server just proxies to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8789',
      '/health': 'http://localhost:8789',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
})
