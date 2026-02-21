#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PUBLIC_DIR="${FRONTEND_DIR}/public"
SRC_LOGO="${PUBLIC_DIR}/scholar_logo.png"
SRC_FAVICON="${PUBLIC_DIR}/scholar_favicon.png"
SRC_FAVICON_ALT="${PUBLIC_DIR}/scholarr_favicon.png"
TMP_DIR="$(mktemp -d)"
TMP_ALPHA="${TMP_DIR}/logo-alpha-mask.png"
TMP_GLYPH="${TMP_DIR}/logo-glyph-white.png"
TMP_CANVAS="${TMP_DIR}/logo-canvas.png"
TMP_ICON="${TMP_DIR}/logo-icon.png"

BRAND_COLOR="${1:-#495e6f}"

if ! command -v magick >/dev/null 2>&1; then
  echo "ImageMagick is required (missing 'magick' command)." >&2
  exit 1
fi

if [[ ! -f "${SRC_LOGO}" ]]; then
  echo "Missing source logo at ${SRC_LOGO}" >&2
  exit 1
fi

if [[ ! -f "${SRC_FAVICON}" && -f "${SRC_FAVICON_ALT}" ]]; then
  SRC_FAVICON="${SRC_FAVICON_ALT}"
fi

mkdir -p "${PUBLIC_DIR}"

if [[ -f "${SRC_FAVICON}" ]]; then
  # Prefer dedicated favicon artwork when provided.
  magick "${SRC_FAVICON}" \
    -background none \
    -gravity center \
    -resize 1024x1024^ \
    -extent 1024x1024 \
    "${TMP_ICON}"
else
  # Build a high-contrast icon from the logo: solid brand background + white logo.
  magick "${SRC_LOGO}" -alpha extract "${TMP_ALPHA}"
  magick -size 1024x1024 xc:white "${TMP_ALPHA}" \
    -compose CopyOpacity \
    -composite \
    "${TMP_GLYPH}"

  magick -size 1024x1024 "xc:${BRAND_COLOR}" "${TMP_CANVAS}"
  magick "${TMP_GLYPH}" -resize 760x760 "${TMP_GLYPH}"
  magick "${TMP_CANVAS}" "${TMP_GLYPH}" \
    -gravity center \
    -compose over \
    -composite \
    "${TMP_ICON}"
fi

magick "${TMP_ICON}" -resize 16x16 "${PUBLIC_DIR}/favicon-16x16.png"
magick "${TMP_ICON}" -resize 32x32 "${PUBLIC_DIR}/favicon-32x32.png"
magick "${TMP_ICON}" -resize 180x180 "${PUBLIC_DIR}/apple-touch-icon.png"
magick "${TMP_ICON}" -resize 192x192 "${PUBLIC_DIR}/android-chrome-192x192.png"
magick "${TMP_ICON}" -resize 512x512 "${PUBLIC_DIR}/android-chrome-512x512.png"
magick \
  \( "${TMP_ICON}" -resize 16x16 \) \
  \( "${TMP_ICON}" -resize 32x32 \) \
  \( "${TMP_ICON}" -resize 48x48 \) \
  "${PUBLIC_DIR}/favicon.ico"

rm -rf "${TMP_DIR}"

echo "Generated favicon + app icon assets in ${PUBLIC_DIR} (logo: ${SRC_LOGO}, favicon source: ${SRC_FAVICON})"
