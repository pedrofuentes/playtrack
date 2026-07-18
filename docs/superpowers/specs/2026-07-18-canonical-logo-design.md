# Canonical PlayTrack Logo Design

**Date:** 2026-07-18  
**Status:** Approved for implementation planning

## Goal

Replace the invented runner/reticle identity with the supplied PlayTrack artwork across the web app, product website, documentation, favicon, and PWA install surfaces. The bright player-only asset is the compact mark; the bright complete logo is reserved for placements large enough to keep its wordmark and tagline readable.

The canonical source files are outside the repository during development:

- `../exchange/playtrack-player-bright.png` — compact player mark
- `../exchange/playtrack-bright.png` — complete logo and tagline

Implementation uses these exact files as the only visual sources. Tracked web assets are deterministic, high-quality resized PNG derivatives with metadata stripped for practical page and PWA weight. They must not redraw, recolor, trace, or generate a substitute logo.

## Selected Visual Direction

### Web app

The top-left brand cell in `WorkspaceShell` uses the bright player-only asset directly on the existing near-black header. The rendered mark is approximately 50 pixels square inside the 56-pixel brand cell. A restrained pale-blue drop shadow separates pale edges from the background without changing the artwork.

The image remains decorative because the existing visually hidden `PlayTrack home` label provides the accessible name. Active-video metadata and top-right actions retain their current positions.

### Product website

The sticky header uses the bright player-only asset beside a readable white `PlayTrack` text label. This keeps the navigation brand recognizable at a 76-pixel header height without shrinking the complete stacked lockup until its tagline becomes illegible.

The complete bright logo appears in larger brand placements:

- website footer
- website 404 page
- repository README header

These placements provide enough rendered area for the supplied wordmark and tagline. The existing social preview remains unchanged because it contains a text treatment rather than the retired logo.

### Favicons and install icons

All compact browser/install artwork derives from the exact bright player-only PNG:

- favicon 16, 32, and 48 pixels
- Apple Touch icon
- standard PWA icons at 192 and 512 pixels
- maskable PWA icons at 192 and 512 pixels

Standard icons use the bright player mark with sufficient padding for small-size recognition. Maskable icons use the current dark PlayTrack background and keep the player inside the maskable safe zone. Icon generation is deterministic resizing/padding only; it does not synthesize or redraw the logo.

## Asset Organization

Tracked web derivatives use explicit names that identify the canonical artwork:

```text
frontend/public/brand/playtrack-player-bright.png
website/assets/playtrack-player-bright.png
website/assets/playtrack-bright.png
```

The player-only web derivative is 512 by 512 pixels, which is sufficient for the app, website header, and favicon/install generation. The complete website logo is 1024 by 1024 pixels so its supplied wordmark and tagline remain legible in the website, 404 page, and README. Both preserve transparency, aspect ratio, colors, and all visible artwork.

The website keeps its assets relative and local for GitHub Pages. The frontend PWA precache includes only the compact player derivative and generated install icons, not the larger complete website logo. The production build must remain below Workbox's per-asset precache limit.

The following retired SVG family is removed after every reference has migrated:

```text
frontend/public/brand/playtrack-mark.svg
frontend/public/brand/playtrack-lockup.svg
frontend/public/brand/playtrack-icon.svg
frontend/public/brand/playtrack-icon-maskable.svg
website/assets/playtrack-lockup.svg
```

## Contrast and Responsive Behavior

- Compact bright marks render directly on PlayTrack's near-black surfaces, matching the approved option C.
- Website header text uses the existing high-contrast foreground color rather than text embedded in a tiny image.
- The player mark never shrinks below the size needed to distinguish the player silhouette and target ring.
- Mobile navigation retains its current controls and spacing; the brand text may reduce in size but remains visible.
- Focus styles, reduced-motion behavior, and page overflow behavior remain unchanged.
- The complete logo uses `object-fit: contain` and preserves its square intrinsic ratio; CSS must not stretch or crop it.
- Web optimization may resize and strip metadata but must not intentionally change colors, transparency, or composition beyond normal high-quality resampling.

## Accessibility

- The app mark stays decorative and relies on the existing hidden `PlayTrack home` label.
- The website header link has an accessible `PlayTrack home` name; its image has an empty alt when adjacent visible text already supplies the brand name.
- Complete-logo-only placements use meaningful `PlayTrack — Follow Every Move` alternative text.
- Logo changes must not remove visible keyboard focus or create an unlabeled navigation target.

## Testing and Verification

Tests are updated before implementation so they fail on the retired asset paths and old markup.

Automated verification covers:

- `WorkspaceShell` references the bright player-only asset and retains its accessible name.
- Website validation requires the compact and complete PNG assets, their intended placements, local relative paths, and useful alt text.
- Website validation rejects references to the retired SVG lockup.
- PWA validation checks every required icon exists and retains the expected dimensions.
- Vite precache configuration includes the canonical brand PNGs and excludes deleted SVGs.
- README references the complete canonical logo.
- Website validation confirms the optimized derivatives remain within their intended dimensions and practical file-size bounds.

Final gates:

```bash
cd frontend
npm test
npm run typecheck
npm run build
npm run test:pwa

cd ..
node website/test-site.mjs
```

Visual verification checks the production web app at desktop and mobile widths, the product website header/footer, the 404 page, favicon/install icons, contrast on dark surfaces, image aspect ratios, overflow, keyboard focus, and reduced motion.

## Out of Scope

- Redesigning or recoloring the supplied artwork
- Changing product copy beyond markup needed for the new header treatment
- Reworking the website layout or editor navigation
- Replacing the existing social preview
- Adding remote assets, fonts, analytics, or runtime dependencies
