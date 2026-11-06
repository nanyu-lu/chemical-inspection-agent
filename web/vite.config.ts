import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发期把 /api 与 /files 代理到本地后端，避免 CORS 与写死域名
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/files': 'http://127.0.0.1:8000',
    },
  },
})
