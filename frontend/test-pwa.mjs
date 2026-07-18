import { existsSync, readFileSync } from 'node:fs'

const required = ['dist/index.html', 'dist/manifest.webmanifest', 'dist/sw.js']
for (const file of required) {
  if (!existsSync(file)) throw new Error(`Run npm run build first: missing ${file}`)
}

const manifest = JSON.parse(readFileSync('dist/manifest.webmanifest', 'utf8'))
const html = readFileSync('dist/index.html', 'utf8')
const worker = readFileSync('dist/sw.js', 'utf8')

if (manifest.name !== 'PlayTrack' || manifest.short_name !== 'PlayTrack') {
  throw new Error('Manifest must use PlayTrack for name and short_name')
}
if (manifest.display !== 'standalone' || manifest.start_url !== './' || manifest.scope !== './') {
  throw new Error('Manifest must be standalone with relative start_url and scope')
}
if (manifest.theme_color !== '#080b0f' || manifest.background_color !== '#080b0f') {
  throw new Error('Manifest must use the PlayTrack dark theme colors')
}

const iconKeys = new Set(manifest.icons.map((icon) => `${icon.sizes}:${icon.purpose}`))
for (const expected of ['192x192:any', '512x512:any', '192x192:maskable', '512x512:maskable']) {
  if (!iconKeys.has(expected)) throw new Error(`Manifest missing icon declaration ${expected}`)
}

if (!html.includes('<title>PlayTrack</title>') || !html.includes('rel="manifest"')) {
  throw new Error('Built shell is missing PlayTrack title or manifest link')
}
if (!worker.includes('precacheAndRoute')) throw new Error('Generated service worker is missing app-shell precache')
for (const forbidden of ['url:"api/', 'url:"ws/', 'url:"data/', 'url:"exports/', '.mp4",revision']) {
  if (worker.includes(forbidden)) throw new Error(`Service-worker precache contains forbidden runtime entry: ${forbidden}`)
}
for (const denied of ['/^\\/api', '/^\\/ws', '/^\\/exports', '/^\\/data', 'mp4|mov|mkv|webm']) {
  if (!worker.includes(denied)) throw new Error(`Navigation fallback is missing deny rule: ${denied}`)
}

console.log(`PlayTrack PWA validation passed (${manifest.icons.length} icons)`)
