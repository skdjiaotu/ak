import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 开发时把 /api 请求代理到后端，避免跨域
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true
      }
    }
  }
})
