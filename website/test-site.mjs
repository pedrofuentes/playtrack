import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const requiredFiles = ['index.html', '404.html', 'styles.css', 'site.js']
const errors = []

function pngDimensions(path) {
  const image = readFileSync(path)
  const signature = image.subarray(0, 8).toString('hex')
  if (signature !== '89504e470d0a1a0a') throw new Error(`not a PNG: ${path}`)
  return { width: image.readUInt32BE(16), height: image.readUInt32BE(20) }
}

for (const file of requiredFiles) {
  if (!existsSync(join(root, file))) errors.push(`missing website/${file}`)
}

if (errors.length === 0) {
  const html = readFileSync(join(root, 'index.html'), 'utf8')
  const notFound = readFileSync(join(root, '404.html'), 'utf8')
  const css = readFileSync(join(root, 'styles.css'), 'utf8')
  const script = readFileSync(join(root, 'site.js'), 'utf8')
  const readme = readFileSync(join(root, '..', 'README.md'), 'utf8')
  const brandFiles = {
    'assets/playtrack-player-bright.png': { width: 512, height: 512, maxBytes: 1_000_000 },
    'assets/playtrack-bright.png': { width: 1024, height: 1024, maxBytes: 2_000_000 },
  }
  for (const [relative, expected] of Object.entries(brandFiles)) {
    const path = join(root, relative)
    if (!existsSync(path)) {
      errors.push(`missing website/${relative}`)
      continue
    }
    const dimensions = pngDimensions(path)
    if (dimensions.width !== expected.width || dimensions.height !== expected.height) {
      errors.push(`website/${relative} must be ${expected.width}x${expected.height}`)
    }
    if (readFileSync(path).byteLength > expected.maxBytes) {
      errors.push(`website/${relative} exceeds ${expected.maxBytes} bytes`)
    }
  }

  for (const requiredHeaderMarkup of [
    'class="brand-mark" src="assets/playtrack-player-bright.png" alt=""',
    '<span class="brand-name">PlayTrack</span>',
  ]) {
    if (!html.includes(requiredHeaderMarkup)) {
      errors.push(`missing canonical header brand markup: ${requiredHeaderMarkup}`)
    }
  }
  const completeLogoMarkup = 'src="assets/playtrack-bright.png" alt="PlayTrack — Follow Every Move"'
  if (!html.includes(completeLogoMarkup)) {
    errors.push('website footer must use the complete canonical logo')
  }
  if (!notFound.includes(completeLogoMarkup)) {
    errors.push('website 404 page must use the complete canonical logo')
  }
  if (!readme.includes('website/assets/playtrack-bright.png')) {
    errors.push('README must use the complete canonical logo')
  }
  for (const retired of ['playtrack-lockup.svg', 'playtrack-mark.svg']) {
    if (html.includes(retired) || notFound.includes(retired) || readme.includes(retired)) {
      errors.push(`retired brand asset remains: ${retired}`)
    }
  }
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
    '<th>System</th><th>SAM 2 tracking</th><th>Notes</th>',
    'Bring your own footage',
    'Scrub to a clear frame and click the player.',
    'Windows',
    'macOS',
  ]
  for (const text of requiredText) {
    if (!html.includes(text)) errors.push(`missing required content: ${text}`)
  }

  const normalizedHtml = html.toLowerCase()
  const forbiddenText = [
    [
      'text',
      'selection',
    ].join(' '),
    [
      'optional',
      'model',
      'license',
    ].join(' '),
    [
      'research',
      'license',
    ].join(' '),
    [
      'text',
      'grounding',
    ].join(' '),
    [
      'non',
      'commercial',
    ].join('-'),
  ]
  for (const text of forbiddenText) {
    if (normalizedHtml.includes(text)) errors.push(`retired website content remains: ${text}`)
  }

  const hardwareSection = html.match(/<section\b[^>]*\bid=["']hardware["'][^>]*>[\s\S]*?<\/section>/)?.[0]
  if (!hardwareSection) {
    errors.push('hardware section is unavailable for table validation')
  } else {
    const hardwareRows = [...hardwareSection.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/g)]
    if (hardwareRows.length === 0) errors.push('hardware table must contain rows')
    for (const [index, row] of hardwareRows.entries()) {
      const cellCount = [...row[1].matchAll(/<t[hd]\b/g)].length
      if (cellCount !== 3) {
        errors.push(`hardware table row ${index + 1} must contain exactly three cells`)
      }
    }
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
    const isDecorativeHeaderMark = tag.includes('class="brand-mark"') && alt === ''
    if (!alt?.trim() && !isDecorativeHeaderMark) {
      errors.push(`image missing useful alt text: ${src ?? tag}`)
    }
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
