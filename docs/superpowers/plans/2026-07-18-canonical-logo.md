# Canonical PlayTrack Logo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the invented runner/reticle identity with web-optimized derivatives of the supplied bright PlayTrack player and complete logo across the app, website, README, favicon, and PWA install surfaces.

**Architecture:** A small Pillow-based build script treats `../exchange/playtrack-player-bright.png` and `../exchange/playtrack-bright.png` as the only canonical sources, trims only transparent margins, and emits deterministic PNG derivatives and install icons. The React app consumes the compact bright player mark; the website uses the compact mark plus readable text in navigation and the complete bright logo in larger placements.

**Tech Stack:** Python 3.12 + Pillow, React 19 + TypeScript, Vite 6, `vite-plugin-pwa` 1.3, dependency-free website HTML/CSS/Node validator, pytest, Vitest.

## Global Constraints

- Canonical sources are exactly `../exchange/playtrack-player-bright.png` and `../exchange/playtrack-bright.png`.
- Do not redraw, recolor, trace, synthesize, or substitute the supplied artwork.
- Web optimization may trim fully transparent margins, resize with Lanczos, strip metadata, and apply dark icon padding; it must not intentionally change visible colors or composition.
- The app top-left uses the bright player-only asset directly on the near-black header, matching approved option C.
- The website header uses the bright player-only asset beside visible white `PlayTrack` text, matching approved option B.
- The complete bright logo is used only where its wordmark and tagline remain readable: website footer, website 404 page, and README.
- The player web derivative is exactly 512×512; the complete website derivative is exactly 1024×1024.
- PWA icon dimensions remain 192×192 and 512×512 for both `any` and `maskable`; Apple Touch remains 180×180; favicons remain 16×16, 32×32, and 48×48.
- Website assets remain relative and local. Add no remote fonts, analytics, cookies, or third-party runtime resources.
- PWA precache remains app-shell-only. Add no runtime caching for `/api`, `/ws`, media, `exports/`, or `data/`.
- The existing `website/assets/social-preview.jpg` remains unchanged.
- Preserve keyboard focus, reduced motion, responsive layout, alt text, and the existing hidden `PlayTrack home` app label.

---

### Task 1: Generate Canonical Brand Derivatives and Install Icons

**Files:**
- Create: `scripts/build_brand_assets.py`
- Create: `backend/tests/test_brand_assets.py`
- Create: `frontend/public/brand/playtrack-player-bright.png`
- Create: `website/assets/playtrack-player-bright.png`
- Create: `website/assets/playtrack-bright.png`
- Replace: `frontend/public/favicon-16.png`
- Replace: `frontend/public/favicon-32.png`
- Replace: `frontend/public/favicon-48.png`
- Replace: `frontend/public/apple-touch-icon.png`
- Replace: `frontend/public/pwa-192x192.png`
- Replace: `frontend/public/pwa-512x512.png`
- Replace: `frontend/public/pwa-maskable-192x192.png`
- Replace: `frontend/public/pwa-maskable-512x512.png`

**Interfaces:**
- Consumes: canonical source directory containing `playtrack-player-bright.png` and `playtrack-bright.png`.
- Produces: `build_brand_assets(source_dir: Path, repo_root: Path) -> tuple[Path, ...]` and the exact tracked asset paths listed above.

- [ ] **Step 1: Write the failing brand-builder tests**

Create `backend/tests/test_brand_assets.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.build_brand_assets import build_brand_assets  # noqa: E402


def source_logo(path: Path, *, size: int, color: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 5
    draw.rectangle((margin, margin, size - margin, size - margin), fill=color)
    image.save(path)


def test_brand_builder_emits_expected_assets_and_dimensions(tmp_path: Path) -> None:
    source_dir = tmp_path / "exchange"
    repo_root = tmp_path / "repo"
    source_dir.mkdir()
    source_logo(source_dir / "playtrack-player-bright.png", size=144, color=(31, 183, 255, 255))
    source_logo(source_dir / "playtrack-bright.png", size=204, color=(99, 255, 128, 255))

    outputs = build_brand_assets(source_dir=source_dir, repo_root=repo_root)

    expected = {
        "frontend/public/brand/playtrack-player-bright.png": (512, 512),
        "website/assets/playtrack-player-bright.png": (512, 512),
        "website/assets/playtrack-bright.png": (1024, 1024),
        "frontend/public/favicon-16.png": (16, 16),
        "frontend/public/favicon-32.png": (32, 32),
        "frontend/public/favicon-48.png": (48, 48),
        "frontend/public/apple-touch-icon.png": (180, 180),
        "frontend/public/pwa-192x192.png": (192, 192),
        "frontend/public/pwa-512x512.png": (512, 512),
        "frontend/public/pwa-maskable-192x192.png": (192, 192),
        "frontend/public/pwa-maskable-512x512.png": (512, 512),
    }
    assert {str(path.relative_to(repo_root)) for path in outputs} == set(expected)
    for relative, dimensions in expected.items():
        with Image.open(repo_root / relative) as image:
            assert image.size == dimensions
            assert image.mode == "RGBA"


def test_install_icons_use_opaque_dark_canvas_and_maskable_safe_zone(tmp_path: Path) -> None:
    source_dir = tmp_path / "exchange"
    repo_root = tmp_path / "repo"
    source_dir.mkdir()
    source_logo(source_dir / "playtrack-player-bright.png", size=144, color=(31, 183, 255, 255))
    source_logo(source_dir / "playtrack-bright.png", size=204, color=(99, 255, 128, 255))

    build_brand_assets(source_dir=source_dir, repo_root=repo_root)

    with Image.open(repo_root / "frontend/public/pwa-512x512.png").convert("RGBA") as standard:
        assert standard.getpixel((0, 0)) == (8, 13, 20, 255)
        assert standard.getpixel((256, 256))[:3] == (31, 183, 255)
    with Image.open(repo_root / "frontend/public/pwa-maskable-512x512.png").convert("RGBA") as maskable:
        assert maskable.getpixel((0, 0)) == (8, 13, 20, 255)
        assert maskable.getpixel((256, 256))[:3] == (31, 183, 255)
        assert maskable.getpixel((64, 64)) == (8, 13, 20, 255)


def test_committed_web_derivatives_stay_within_weight_budget() -> None:
    expected = {
        ROOT / "frontend/public/brand/playtrack-player-bright.png": (512, 512, 1_000_000),
        ROOT / "website/assets/playtrack-player-bright.png": (512, 512, 1_000_000),
        ROOT / "website/assets/playtrack-bright.png": (1024, 1024, 2_000_000),
    }
    for path, (width, height, max_bytes) in expected.items():
        assert path.is_file()
        assert path.stat().st_size <= max_bytes
        with Image.open(path) as image:
            assert image.size == (width, height)
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-logo-uv uv run --extra dev pytest tests/test_brand_assets.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.build_brand_assets'` because the generator does not exist.

- [ ] **Step 3: Implement the deterministic asset builder**

Create `scripts/build_brand_assets.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

DARK = (8, 13, 20, 255)


def prepared_artwork(
    source: Image.Image,
    *,
    size: int,
    fill_ratio: float,
    background: tuple[int, int, int, int] | None,
) -> Image.Image:
    artwork = source.convert("RGBA")
    bounds = artwork.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("Brand source has no visible pixels")
    artwork = artwork.crop(bounds)
    target = max(1, round(size * fill_ratio))
    artwork.thumbnail((target, target), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), background or (0, 0, 0, 0))
    offset = ((size - artwork.width) // 2, (size - artwork.height) // 2)
    canvas.alpha_composite(artwork, offset)
    return canvas


def save_png(image: Image.Image, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True, compress_level=9)
    return destination


def build_brand_assets(*, source_dir: Path, repo_root: Path) -> tuple[Path, ...]:
    with Image.open(source_dir / "playtrack-player-bright.png") as image:
        player_source = image.convert("RGBA")
    with Image.open(source_dir / "playtrack-bright.png") as image:
        complete_source = image.convert("RGBA")
    outputs: list[Path] = []

    player_web = prepared_artwork(
        player_source, size=512, fill_ratio=0.88, background=None
    )
    outputs.append(save_png(
        player_web, repo_root / "frontend/public/brand/playtrack-player-bright.png"
    ))
    outputs.append(save_png(
        player_web, repo_root / "website/assets/playtrack-player-bright.png"
    ))
    outputs.append(save_png(
        prepared_artwork(complete_source, size=1024, fill_ratio=0.90, background=None),
        repo_root / "website/assets/playtrack-bright.png",
    ))

    icon_specs = {
        "favicon-16.png": (16, 0.84),
        "favicon-32.png": (32, 0.84),
        "favicon-48.png": (48, 0.84),
        "apple-touch-icon.png": (180, 0.78),
        "pwa-192x192.png": (192, 0.82),
        "pwa-512x512.png": (512, 0.82),
        "pwa-maskable-192x192.png": (192, 0.64),
        "pwa-maskable-512x512.png": (512, 0.64),
    }
    for filename, (size, fill_ratio) in icon_specs.items():
        outputs.append(save_png(
            prepared_artwork(
                player_source,
                size=size,
                fill_ratio=fill_ratio,
                background=DARK,
            ),
            repo_root / "frontend/public" / filename,
        ))
    return tuple(outputs)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build PlayTrack brand derivatives")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=repo_root.parent / "exchange",
    )
    args = parser.parse_args()
    for path in build_brand_assets(source_dir=args.source_dir, repo_root=repo_root):
        print(path.relative_to(repo_root))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate tracked derivatives from the supplied sources**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-logo-uv uv run python ../scripts/build_brand_assets.py
```

Expected: eleven relative asset paths print, including `frontend/public/brand/playtrack-player-bright.png` and `website/assets/playtrack-bright.png`. No network, model weight, or GPU is used.

- [ ] **Step 5: Run the focused tests to verify GREEN**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-logo-uv uv run --extra dev pytest tests/test_brand_assets.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Inspect generated artwork**

Open these files with the image viewer and confirm the player is centered, no visible artwork is clipped, transparent web derivatives remain transparent, and icon backgrounds are `#080d14`:

```text
frontend/public/brand/playtrack-player-bright.png
website/assets/playtrack-bright.png
frontend/public/favicon-32.png
frontend/public/pwa-512x512.png
frontend/public/pwa-maskable-512x512.png
```

- [ ] **Step 7: Commit the generator and generated assets**

```bash
git add scripts/build_brand_assets.py backend/tests/test_brand_assets.py \
  frontend/public/brand/playtrack-player-bright.png \
  website/assets/playtrack-player-bright.png website/assets/playtrack-bright.png \
  frontend/public/favicon-16.png frontend/public/favicon-32.png frontend/public/favicon-48.png \
  frontend/public/apple-touch-icon.png frontend/public/pwa-192x192.png \
  frontend/public/pwa-512x512.png frontend/public/pwa-maskable-192x192.png \
  frontend/public/pwa-maskable-512x512.png
git commit -m "Generate canonical PlayTrack brand assets"
```

---

### Task 2: Use the Bright Player Mark in the Web App and PWA

**Files:**
- Modify: `frontend/src/components/WorkspaceShell.test.tsx`
- Modify: `frontend/src/components/WorkspaceShell.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/vite.config.ts`
- Delete: `frontend/public/brand/playtrack-mark.svg`
- Delete: `frontend/public/brand/playtrack-lockup.svg`
- Delete: `frontend/public/brand/playtrack-icon.svg`
- Delete: `frontend/public/brand/playtrack-icon-maskable.svg`

**Interfaces:**
- Consumes: `frontend/public/brand/playtrack-player-bright.png` from Task 1.
- Produces: app top-left brand markup and PWA precache configuration with no retired SVG references.

- [ ] **Step 1: Change the workspace test to require the canonical mark**

Replace the brand assertions in `frontend/src/components/WorkspaceShell.test.tsx` with:

```ts
  expect(markup).toContain('aria-label="PlayTrack home"')
  expect(markup).toContain('src="/brand/playtrack-player-bright.png"')
  expect(markup).toContain('aria-hidden="true"')
  expect(markup).not.toContain('playtrack-mark.svg')
  expect(markup).not.toContain('aria-label="FindMe"')
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```bash
cd frontend
npm test -- --run src/components/WorkspaceShell.test.tsx
```

Expected: FAIL because `WorkspaceShell` still renders `/brand/playtrack-mark.svg`.

- [ ] **Step 3: Point `WorkspaceShell` at the bright player mark**

In `frontend/src/components/WorkspaceShell.tsx`, replace the existing brand image with:

```tsx
        <div className="playtrack-mark">
          <img
            src="/brand/playtrack-player-bright.png"
            alt=""
            aria-hidden="true"
          />
          <span className="sr-only" aria-label="PlayTrack home">PlayTrack</span>
        </div>
```

- [ ] **Step 4: Apply the approved direct-on-dark contrast treatment**

Replace the `.playtrack-mark img` rule in `frontend/src/styles.css` with:

```css
.playtrack-mark {
  overflow: hidden;
}

.playtrack-mark img {
  display: block;
  width: 50px;
  height: 50px;
  object-fit: contain;
  filter: drop-shadow(0 0 8px rgba(123, 221, 255, 0.34));
}
```

Inside `@media (max-width: 1100px)`, add:

```css
  .playtrack-mark img { width: 46px; height: 46px; }
```

Inside `@media (max-width: 860px)`, keep the existing border override and add:

```css
  .playtrack-mark img { width: 42px; height: 42px; }
```

- [ ] **Step 5: Update the PWA app-shell asset list**

In `frontend/vite.config.ts`, replace the two retired brand entries in `includeAssets` with:

```ts
      includeAssets: [
        'brand/playtrack-player-bright.png',
        'favicon-16.png',
        'favicon-32.png',
        'favicon-48.png',
        'apple-touch-icon.png',
      ],
```

Do not change `globPatterns`, `globIgnores`, `navigateFallbackDenylist`, or `runtimeCaching`.

- [ ] **Step 6: Delete the retired frontend SVG family**

Delete exactly:

```text
frontend/public/brand/playtrack-mark.svg
frontend/public/brand/playtrack-lockup.svg
frontend/public/brand/playtrack-icon.svg
frontend/public/brand/playtrack-icon-maskable.svg
```

- [ ] **Step 7: Run focused and build verification**

Run:

```bash
cd frontend
npm test -- --run src/components/WorkspaceShell.test.tsx
npm run typecheck
npm run build
npm run test:pwa
```

Expected: workspace tests pass, typecheck exits 0, Vite builds without Workbox maximum-file-size errors, and PWA validation reports four icons.

- [ ] **Step 8: Verify the generated service worker boundaries**

Run:

```bash
cd frontend
rg -n 'playtrack-player-bright|playtrack-(mark|lockup|icon)\.svg|api/|ws/|exports/|data/' dist/sw.js
```

Expected: the bright player PNG appears; no retired SVG appears; `/api`, `/ws`, `/exports`, and `/data` appear only in navigation-deny logic, not runtime cache entries.

- [ ] **Step 9: Commit the web-app migration**

```bash
git add frontend/src/components/WorkspaceShell.test.tsx \
  frontend/src/components/WorkspaceShell.tsx frontend/src/styles.css \
  frontend/vite.config.ts frontend/public/brand
git commit -m "Use canonical PlayTrack mark in web app"
```

---

### Task 3: Use the Canonical Logo on the Website and README

**Files:**
- Modify: `website/test-site.mjs`
- Modify: `website/index.html`
- Modify: `website/404.html`
- Modify: `website/styles.css`
- Modify: `README.md`
- Delete: `website/assets/playtrack-lockup.svg`

**Interfaces:**
- Consumes: `website/assets/playtrack-player-bright.png` and `website/assets/playtrack-bright.png` from Task 1.
- Produces: relative/local website branding, a readable navigation brand, complete-logo large placements, and no current product references to the retired SVG family.

- [ ] **Step 1: Extend the dependency-free website validator first**

In `website/test-site.mjs`, add this helper after `const errors = []`:

```js
function pngDimensions(path) {
  const image = readFileSync(path)
  const signature = image.subarray(0, 8).toString('hex')
  if (signature !== '89504e470d0a1a0a') throw new Error(`not a PNG: ${path}`)
  return { width: image.readUInt32BE(16), height: image.readUInt32BE(20) }
}
```

Add these brand requirements inside the existing `errors.length === 0` block:

```js
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
```

In the existing `imageTags` validation loop, replace the unconditional useful-alt check:

```js
    if (!alt?.trim()) errors.push(`image missing useful alt text: ${src ?? tag}`)
```

with a decorative-brand exception that is limited to the adjacent-text header mark:

```js
    const isDecorativeHeaderMark = tag.includes('class="brand-mark"') && alt === ''
    if (!alt?.trim() && !isDecorativeHeaderMark) {
      errors.push(`image missing useful alt text: ${src ?? tag}`)
    }
```

- [ ] **Step 2: Run the website validator to verify RED**

Run:

```bash
node website/test-site.mjs
```

Expected: FAIL with missing canonical brand markup, the README still using the SVG lockup, and retired asset references.

- [ ] **Step 3: Replace the website favicon and header brand**

In `website/index.html`, replace the favicon link with:

```html
    <link rel="icon" href="assets/playtrack-player-bright.png" type="image/png">
```

Replace the header brand link with:

```html
      <a class="brand" href="./" aria-label="PlayTrack home">
        <img class="brand-mark" src="assets/playtrack-player-bright.png" alt="">
        <span class="brand-name">PlayTrack</span>
      </a>
```

- [ ] **Step 4: Replace the footer and 404 large-logo placements**

In `website/index.html`, replace the footer image with:

```html
      <img class="complete-logo" src="assets/playtrack-bright.png" alt="PlayTrack — Follow Every Move" width="1024" height="1024">
```

In `website/404.html`, replace the current logo with:

```html
        <img class="complete-logo" src="assets/playtrack-bright.png" alt="PlayTrack — Follow Every Move" width="1024" height="1024">
```

- [ ] **Step 5: Implement the approved website contrast and responsive sizing**

In `website/styles.css`, replace `.brand { width: 174px; text-decoration: none; }` with:

```css
.brand {
  display: inline-flex;
  align-items: center;
  gap: .55rem;
  color: var(--ink);
  text-decoration: none;
}
.brand-mark {
  width: 58px;
  height: 58px;
  object-fit: contain;
  filter: drop-shadow(0 0 9px rgba(123, 221, 255, .32));
}
.brand-name { font-size: 1.2rem; font-weight: 900; letter-spacing: -.04em; }
```

Replace `footer img { width: 150px; }` with:

```css
footer .complete-logo { width: 150px; height: 150px; object-fit: contain; }
```

Inside `@media (max-width: 680px)`, replace `.brand { width: 145px; }` with:

```css
  .brand { gap: .35rem; }
  .brand-mark { width: 50px; height: 50px; }
  .brand-name { font-size: 1rem; }
```

In the inline 404 styles, replace `.not-found img` with:

```css
      .not-found .complete-logo { width: min(280px, 72vw); margin: 0 auto 2rem; }
```

- [ ] **Step 6: Point the README at the complete canonical logo**

Replace the first image in `README.md` with:

```html
  <img src="website/assets/playtrack-bright.png" width="360" alt="PlayTrack — Follow Every Move">
```

- [ ] **Step 7: Delete the retired website lockup**

Delete exactly:

```text
website/assets/playtrack-lockup.svg
```

- [ ] **Step 8: Run focused website verification**

Run:

```bash
node website/test-site.mjs
git grep -n -E 'playtrack-(mark|lockup|icon)(-maskable)?\.svg' -- frontend website README.md
```

Expected: website validation passes and `git grep` exits 1 with no matches.

- [ ] **Step 9: Run all repository gates**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-logo-uv uv run --extra dev pytest -m "not integration"

cd ../frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:pwa

cd ..
node website/test-site.mjs
git diff --check
```

Expected: backend weight-free suite passes, frontend suite passes, typecheck/build/PWA pass, website validation passes, and `git diff --check` prints nothing.

- [ ] **Step 10: Perform visual and accessibility checks**

Inspect the actual production build at desktop and mobile widths and confirm:

```text
- App top-left uses the bright player mark, remains inside the 56px/46px brand cell, and separates from the dark header.
- Active video title and Open video action do not shift or overlap.
- Website header shows the bright mark plus readable PlayTrack text on desktop and mobile.
- Website footer and 404 show the complete logo without stretching, clipping, or overflow.
- Favicon, Apple Touch, standard PWA, and maskable PWA icons are centered and recognizable.
- Keyboard focus remains visible on website links and navigation.
- Reduced-motion mode still disables reveal transitions.
- No horizontal overflow appears at 320px width.
```

Use the local image viewer to inspect the generated favicon/PWA PNGs at original resolution and visually confirm the selected bright colors were preserved.

- [ ] **Step 11: Commit the website and documentation migration**

```bash
git add website/index.html website/404.html website/styles.css website/test-site.mjs \
  website/assets/playtrack-player-bright.png website/assets/playtrack-bright.png \
  website/assets/playtrack-lockup.svg README.md
git commit -m "Use canonical PlayTrack logo on website"
```
