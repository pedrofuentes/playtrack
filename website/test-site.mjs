import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const requiredFiles = ['index.html', '404.html', 'styles.css', 'site.js']
const errors = []

for (const file of requiredFiles) {
  if (!existsSync(join(root, file))) errors.push(`missing website/${file}`)
}

if (errors.length === 0) {
  const html = readFileSync(join(root, 'index.html'), 'utf8')
  const notFound = readFileSync(join(root, '404.html'), 'utf8')
  const css = readFileSync(join(root, 'styles.css'), 'utf8')
  const script = readFileSync(join(root, 'site.js'), 'utf8')
  const sections = [
    'problem', 'workflow', 'screenshots', 'benefits', 'hardware',
    'install', 'usage', 'limitations', 'community',
  ]
  for (const id of sections) {
    if (!new RegExp(`<section[^>]+id=["']${id}["']`).test(html)) {
      errors.push(`missing #${id} section`)
    }
  }

  const requiredText = [
    '<title>PlayTrack',
    'name="description"',
    'property="og:title"',
    'property="og:description"',
    'property="og:image"',
    'name="twitter:card"',
    'rel="canonical" href="https://pf.run/playtrack/"',
    'https://github.com/pedrofuentes/playtrack',
    'https://github.com/pedrofuentes/playtrack/issues/new?template=bug_report.yml',
    'https://github.com/pedrofuentes/playtrack/issues/new?template=feature_request.yml',
    'LocateAnything',
    'non-commercial',
    'Windows',
    'macOS',
  ]
  for (const text of requiredText) {
    if (!html.includes(text)) errors.push(`missing required content: ${text}`)
  }

  const imageTags = [...html.matchAll(/<img\b[^>]*>/g)].map((match) => match[0])
  if (imageTags.length < 4) errors.push('expected logo and three product screenshots')
  for (const tag of imageTags) {
    const src = tag.match(/\bsrc=["']([^"']+)["']/)?.[1]
    const alt = tag.match(/\balt=["']([^"']*)["']/)?.[1]
    if (!src) errors.push(`image missing src: ${tag}`)
    else if (/^(?:https?:)?\/\//.test(src) || src.startsWith('/')) {
      errors.push(`image asset must be relative: ${src}`)
    } else if (!existsSync(join(root, src))) {
      errors.push(`missing local image: ${src}`)
    }
    if (!alt?.trim()) errors.push(`image missing useful alt text: ${src ?? tag}`)
  }

  for (const match of html.matchAll(/\b(?:src|href)=["']([^"']+)["']/g)) {
    const ref = match[1]
    if (/^(?:https?:|mailto:|#)/.test(ref)) continue
    if (ref.startsWith('/')) {
      errors.push(`root-relative asset is not project-path safe: ${ref}`)
      continue
    }
    const clean = ref.split(/[?#]/)[0]
    if (clean && !existsSync(join(root, clean))) errors.push(`missing local reference: ${ref}`)
  }

  if (!css.includes(':focus-visible')) errors.push('missing visible focus styles')
  if (!css.includes('prefers-reduced-motion')) errors.push('missing reduced-motion styles')
  if (!css.includes('@media')) errors.push('missing responsive styles')
  if (!/img\s*\{[^}]*height:\s*auto\b/.test(css)) {
    errors.push('responsive images must preserve their intrinsic aspect ratio with height: auto')
  }
  if (!script.includes('IntersectionObserver')) errors.push('missing progressive reveal behavior')
  if (!notFound.includes('PlayTrack') || !notFound.includes('href="./"')) {
    errors.push('404 page must link back to the PlayTrack site root')
  }
}

const workflowPath = join(root, '..', '.github', 'workflows', 'pages.yml')
if (!existsSync(workflowPath)) {
  errors.push('missing GitHub Pages workflow')
} else {
  const workflow = readFileSync(workflowPath, 'utf8')
  for (const action of ['actions/configure-pages@', 'actions/upload-pages-artifact@', 'actions/deploy-pages@']) {
    if (!workflow.includes(action)) errors.push(`Pages workflow missing ${action}`)
  }
  if (!workflow.includes('path: website')) errors.push('Pages workflow must upload website/')
}

for (const form of ['bug_report.yml', 'feature_request.yml', 'config.yml']) {
  const formPath = join(root, '..', '.github', 'ISSUE_TEMPLATE', form)
  if (!existsSync(formPath)) errors.push(`missing issue template ${form}`)
}

if (errors.length) {
  console.error(errors.map((error) => `- ${error}`).join('\n'))
  process.exit(1)
}

console.log('PlayTrack website validation passed')
