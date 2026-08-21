import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendUrl = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
      '/offset': {
        target: backendUrl,
        changeOrigin: true,
      },
      '/renders': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
