// Cloudflare Pages 新版校验器会拒绝 Slidev 自动生成的 `/* /index.html 200`
// 规则（判定为无限循环，error 100324）。构建后删除它，保留 404.html 兜底。
import { rmSync } from 'node:fs'

rmSync('dist/_redirects', { force: true })
console.log('[clean] removed dist/_redirects (SPA fallback handled by 404.html)')
