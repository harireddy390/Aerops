import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// AeroOps console. Dev proxy -> FastAPI :8000 (no CORS pain, same-origin /api).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: { outDir: 'dist' },
})
