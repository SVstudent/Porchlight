import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Set VITE_PROXY_TARGET in frontend/.env.local if your backend is not on :8000
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': { target: env.VITE_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true },
      },
    },
  };
});
