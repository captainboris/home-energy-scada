# Current Readings scene

`current-house.webp` is a clean static scene generated from the user-approved house reference on 2026-10-21. All UI cards, text, values and energy arrows were removed with image generation; the result was encoded as WebP without changing geometry. It is not a pixel-exact source export, and the house / panels / wall devices are a single image because original separated assets were not supplied.

Readings and animated SVG connections are rendered independently by `CurrentReadings.tsx`. Its paths use this image's 1557×1010 coordinates. Import with Vite `?inline`: the existing Web CSP allows `data:` images, and the static handler does not serve binary WebP. Do not switch this to a public image URL without checking both constraints. No backend change is needed.
