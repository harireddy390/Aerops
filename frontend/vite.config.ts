import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// AeroOps console. Dev proxy -> FastAPI :8000 (no CORS pain, same-origin /api).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: { outDir: 'dist' },
})
