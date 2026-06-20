import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// Build output goes into Flask's static/ folder so the existing static handler
// serves it. base must match that public path. Client routing uses HashRouter,
// so no server-side route config is needed.
export default defineConfig({
  plugins: [react()],
  base: '/static/spa/',
  build: {
    outDir: resolve(__dirname, '../static/spa'),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://10.0.60.155:8181',
      '/login': 'http://10.0.60.155:8181',
    },
  },
})
