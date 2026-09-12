import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Set VITE_PROXY_TARGET in frontend/.env.local if your backend is not on :8000
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    server: {
      // The backend builds every check-in link from PUBLIC_BASE_URL. If Vite silently moves to the next free
      // port, those links point at whatever else is running there, so fail loudly instead.
      port: 5173,
      strictPort: true,
      // A tunnel (ngrok, cloudflared) reaches this server under a hostname it does not know, and Vite
      // refuses unknown hosts with "Blocked request" rather than serving the app. Check-in links are
      // meant to be opened on a phone, so tunnelled hosts have to be allowed.
      allowedHosts: ['.ngrok-free.dev', '.ngrok-free.app', '.ngrok.io', '.trycloudflare.com', 'localhost'],
      proxy: {
        '/api': { target: env.VITE_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true },
      },
    },
  };
});
