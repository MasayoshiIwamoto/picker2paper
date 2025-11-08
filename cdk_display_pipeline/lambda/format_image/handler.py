import json
import logging
import os
import traceback
from io import BytesIO
from typing import Iterable

import boto3
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# Enable HEIC/HEIF/AVIF support if pillow-heif is available
try:  # pragma: no cover - optional dependency
    import pillow_heif

    pillow_heif.register_heif_opener()
    try:
        pillow_heif.register_avif_opener()
    except Exception:
        # Older pillow-heif may not expose register_avif_opener
        pass
except Exception:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

s3 = boto3.client("s3")
DEST_BUCKET = os.environ.get("DEST_BUCKET")
PROCESSED_PREFIX = os.environ.get("PROCESSED_PREFIX", "processed/")
TARGET_WIDTH = int(os.environ.get("TARGET_WIDTH", "800"))
TARGET_HEIGHT = int(os.environ.get("TARGET_HEIGHT", "480"))
ROTATE = int(os.environ.get("ROTATE", "0"))
SATURATION = float(os.environ.get("SATURATION", "1.2"))
AUTO_CONTRAST = os.environ.get("AUTO_CONTRAST", "1").strip().lower() in {"1", "true", "yes", "on"}
AUTO_CONTRAST_CUTOFF = float(os.environ.get("AUTO_CONTRAST_CUTOFF", "0"))
BRIGHTNESS = float(os.environ.get("BRIGHTNESS", "1.0"))
CONTRAST = float(os.environ.get("CONTRAST", "1.05"))
SHARPEN = float(os.environ.get("SHARPEN", "0.0"))
DITHER_MODE = os.environ.get("DITHER", "floyd").strip().lower()
SUPPORTED_EXT = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".gif",
    ".webp",
    ".avif",
    ".heic",
    ".heif",
    ".tif",
    ".tiff",
}

EINK_PALETTE = [
    (0, 0, 0),
    (245, 245, 245),
    (0, 176, 92),
    (0, 112, 192),
    (216, 45, 45),
    (255, 212, 0),
    (255, 152, 0),
]

try:  # Pillow >= 9
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover
    RESAMPLE = Image.LANCZOS

try:
    QUANTIZE_MAXCOVERAGE = Image.Quantize.MAXCOVERAGE  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover
    QUANTIZE_MAXCOVERAGE = 0


def _is_supported(key: str) -> bool:
    lower = key.lower()
    return any(lower.endswith(ext) for ext in SUPPORTED_EXT)


def _build_palette() -> Iterable[int]:
    palette = []
    for rgb in EINK_PALETTE:
        palette.extend(rgb)
    palette.extend([0, 0, 0] * (256 - len(EINK_PALETTE)))
    return palette


PALETTE_IMAGE = Image.new("P", (1, 1))
PALETTE_IMAGE.putpalette(list(_build_palette()))


def _prepare_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")
    if ROTATE:
        image = image.rotate(ROTATE, expand=True)
    fitted = ImageOps.fit(
        image,
        (TARGET_WIDTH, TARGET_HEIGHT),
        method=RESAMPLE,
        centering=(0.5, 0.5),
    )
    if AUTO_CONTRAST:
        fitted = ImageOps.autocontrast(fitted, cutoff=AUTO_CONTRAST_CUTOFF)
    if BRIGHTNESS != 1.0:
        fitted = ImageEnhance.Brightness(fitted).enhance(BRIGHTNESS)
    if CONTRAST != 1.0:
        fitted = ImageEnhance.Contrast(fitted).enhance(CONTRAST)
    if SATURATION != 1.0:
        fitted = ImageEnhance.Color(fitted).enhance(SATURATION)
    if SHARPEN > 0:
        radius = max(0.6, min(2.5, 1.0 + (SHARPEN * 0.8)))
        percent = int(150 + 100 * SHARPEN)
        fitted = fitted.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=3))
    return fitted


def _resolve_dither_mode() -> int:
    if DITHER_MODE in {"none", "off", "0"}:
        return Image.Dither.NONE
    return Image.Dither.FLOYDSTEINBERG


def _quantize(image: Image.Image) -> Image.Image:
    return image.quantize(
        palette=PALETTE_IMAGE,
        dither=_resolve_dither_mode(),
        method=QUANTIZE_MAXCOVERAGE,
    )


def handler(event, _context):
    logger.info("Received event: %s", json.dumps(event))
    if not DEST_BUCKET:
        logger.error("DEST_BUCKET environment variable is not set")
        return {"status": "error", "reason": "missing DEST_BUCKET"}

    for record in event.get("Records", []):
        try:
            src_bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]
            if not _is_supported(key):
                logger.info("Skipping unsupported file: %s", key)
                continue
            if key.startswith(PROCESSED_PREFIX):
                logger.info("Skipping already processed object: %s", key)
                continue

            logger.info("Processing %s/%s", src_bucket, key)
            obj = s3.get_object(Bucket=src_bucket, Key=key)
            original_bytes = obj["Body"].read()

            with Image.open(BytesIO(original_bytes)) as img:
                prepared = _prepare_image(img)
            quantized = _quantize(prepared)

            buffer = BytesIO()
            quantized.save(buffer, format="BMP")
            buffer.seek(0)

            dest_base = os.path.splitext(os.path.basename(key))[0] + ".bmp"
            dest_key = f"{PROCESSED_PREFIX}{dest_base}"
            logger.info("Uploading processed image to %s/%s", DEST_BUCKET, dest_key)
            s3.put_object(
                Bucket=DEST_BUCKET,
                Key=dest_key,
                Body=buffer,
                ContentType="image/bmp",
            )
        except Exception:  # pylint: disable=broad-except
            logger.error("Failed to process record: %s", json.dumps(record))
            logger.error(traceback.format_exc())

    return {"status": "ok"}
