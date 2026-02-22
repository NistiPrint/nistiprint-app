// nistiprint-frontend/vite.config.js
import react from '@vitejs/plugin-react';
import path from "path";
import { defineConfig } from 'vite';

// https://vitejs.dev/config/
export default defineConfig({
  base: "/frontend/", // CRÍTICO: Indica que a app será servida de um subcaminho
  plugins: [
    react({
      babel: {
        plugins: [],
      },
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',  // Use localhost para o backend rodando localmente
        changeOrigin: true,
        credentials: true,
        ws: true,
        configure: (proxy, options) => {
          proxy.on('error', (err, req, res) => {
            console.log('proxy error', err);
          });
          proxy.on('proxyReq', (proxyReq, req, res) => {
            console.log('Sending Request to the Target:', req.method, req.url);
          });
          proxy.on('proxyRes', (proxyRes, req, res) => {
            console.log('Received Response from the Target:', proxyRes.statusCode, req.url);
          });
        },
      },
    },
    cors: {
      origin: 'http://localhost:5173',
      credentials: true,
    },
  },
  preview: { // Para o comando 'vite preview', se usado
    host: '0.0.0.0',
    port: 4173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
