// Vant 图标字体把 woff2 内嵌成 data URI，后面又挂了 at.alicdn.com 的 woff 回退。
// 生产 CSP 的 font-src 只有 'self' 和 data:，浏览器仍会去拉这个外链并记一条违规。
// 只保留内嵌 woff2，图标不依赖外站。

const ALICDN_WOFF = /,url\(\/\/at\.alicdn\.com\/[^)]+\)\s*format\((?:"|')woff(?:"|')\)/g

export function stripAlicdnIconFont(css: string): string {
  return css.replace(ALICDN_WOFF, '')
}
