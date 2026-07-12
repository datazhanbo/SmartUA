import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // 关闭代理缓冲，保证 SSE（/agent/sessions/{id}/stream）逐条实时下发
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache, no-transform'
            proxyRes.headers['x-accel-buffering'] = 'no'
          })
        }
      }
    }
  }
})
