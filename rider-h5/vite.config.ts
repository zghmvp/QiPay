import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig, type Plugin } from 'vite'

import { stripAlicdnIconFont } from './build/strip-alicdn-font.ts'

function stripAlicdnIconFontPlugin(): Plugin {
  return {
    name: 'strip-vant-alicdn-font',
    enforce: 'pre',
    transform(code, id) {
      if (!id.includes('vant') || !code.includes('at.alicdn.com')) return null
      const next = stripAlicdnIconFont(code)
      return next === code ? null : { code: next, map: null }
    },
  }
}

// Q-17：生产构建挂在同域子路径 /rider-h5/。
// 开发服务器仍在站点根路径，本地继续打开 http://localhost:5174/。
// 部署时 Nginx 需：/api 反代到后端；/rider-h5/ 未知路径回落到 index.html（history 刷新不 404）。
const PRODUCTION_BASE = '/rider-h5/'

export default defineConfig(({ mode }) => ({
  base: mode === 'production' ? PRODUCTION_BASE : '/',
  plugins: [stripAlicdnIconFontPlugin(), vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    strictPort: true,
    allowedHosts: ['h5.19970128.xyz'],
  },
  preview: {
    host: '0.0.0.0',
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
