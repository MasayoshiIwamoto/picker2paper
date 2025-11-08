#!/usr/bin/env python3
"""Fetch the next e-paper image from the PhotoPicker mTLS API and display it.

利用例:
  python fetch_next_image.py \\
      --api-url https://epaper.example.com/next-image \\
      --cert /home/pi/certs/device.pem.crt \\
      --key /home/pi/certs/device-private.pem.key \\
      --root-ca /home/pi/certs/myCA.pem \\
      --display

取得した BMP は `.cache` ディレクトリに保存され、同じファイルを再取得せずに表示できます。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError as exc:  # pragma: no cover - requests should be installed on the Pi
    raise SystemExit("The requests package is required: pip install requests") from exc

# Allow import of bundled waveshare_e_paper driver (raspy/lib/waveshare_epd)
LIB_DIR = Path(__file__).resolve().parents[1] / "lib"
if LIB_DIR.exists():
    sys.path.append(str(LIB_DIR))

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow should be installed on the Pi
    Image = None  # type: ignore

LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", help="API Gateway endpoint URL")
    parser.add_argument("--cert", help="クライアント証明書 (mTLS 用)")
    parser.add_argument("--key", help="秘密鍵 (mTLS 用)")
    parser.add_argument(
        "--root-ca",
        help="信頼する CA 証明書のパス (省略時はシステムの証明書ストアを使用)",
    )

    parser.add_argument(
        "--save-dir", default="../pic", help="BMP を保存・キャッシュするディレクトリ"
    )
    parser.add_argument(
        "--display", action="store_true", help="ダウンロード後に e-paper へ表示"
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT, help="待ち時間 (秒)"
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.api_url:
        raise SystemExit("--api-url は必須です")
    missing = [
        name
        for name, value in (
            ("--cert", args.cert),
            ("--key", args.key),
        )
        if not value
    ]
    if missing:
        raise SystemExit("mTLS API 呼び出しには " + ", ".join(missing) + " が必要です")


def fetch_metadata(
    api_url: str,
    cert_path: Path,
    key_path: Path,
    ca_path: Optional[Path],
    timeout: int,
) -> dict:
    LOGGER.info("API %s へ次の画像をリクエスト", api_url)
    response = requests.get(
        api_url,
        cert=(str(cert_path), str(key_path)),
        verify=str(ca_path) if ca_path else True,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    LOGGER.debug("API response: %s", data)
    if "bmp_url" not in data:
        raise ValueError("API 応答に bmp_url が含まれていません")
    return data


def download_bmp(
    url: str,
    dest_dir: Path,
    object_key: str,
    timeout: int,
    verify: object,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(object_key).name
    dest_path = dest_dir / filename
    LOGGER.info("BMP をダウンロード %s", filename)
    with requests.get(url, stream=True, timeout=timeout, verify=verify) as response:
        response.raise_for_status()
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix="epaper_", suffix=".bmp", dir=str(dest_dir)
        )
        try:
            with os.fdopen(tmp_fd, "wb") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        tmp_file.write(chunk)
            Path(tmp_name).replace(dest_path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
    LOGGER.info("BMP を保存しました: %s", dest_path)
    return dest_path


def display_bmp(path: Path) -> None:
    if Image is None:
        LOGGER.error("Pillow がインストールされていないため表示できません")
        return
    try:
        from waveshare_epd import epd7in3f
    except ImportError:
        LOGGER.error(
            "waveshare_epd ライブラリが見つかりません。ドライバをインストールしてください。"
        )
        return

    LOGGER.info("e-paper に描画: %s", path.name)
    epd = epd7in3f.EPD()
    epd.init()
    try:
        epd.Clear()
    except AttributeError:
        pass
    with Image.open(path) as image:
        epd.display(epd.getbuffer(image))
    epd.sleep()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = parse_args()
    validate_args(args)

    cert_path = Path(args.cert).expanduser().resolve()
    key_path = Path(args.key).expanduser().resolve()
    ca_path = Path(args.root_ca).expanduser().resolve() if args.root_ca else None
    for label, path in ("cert", cert_path), ("key", key_path):
        if not path.exists():
            raise SystemExit(f"{label} ファイルが存在しません: {path}")
    if ca_path is not None and not ca_path.exists():
        raise SystemExit(f"root-ca ファイルが存在しません: {ca_path}")
    metadata = fetch_metadata(args.api_url, cert_path, key_path, ca_path, args.timeout)

    bmp_url = metadata["bmp_url"]
    object_key = metadata.get("object_key", f"image-{int(time.time())}.bmp")
    base_dir = Path(args.save_dir).expanduser().resolve()
    cache_dir = (base_dir / ".cache").resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / Path(object_key).name

    if cache_path.exists():
        LOGGER.info("キャッシュ済みの BMP を使用します: %s", cache_path)
        bmp_path = cache_path
    else:
        try:
            verify_arg: object = str(ca_path) if ca_path else True
            bmp_path = download_bmp(
                bmp_url, cache_dir, object_key, args.timeout, verify_arg
            )
        except Exception as err:
            LOGGER.error("BMP ダウンロードに失敗しました: %s", err, exc_info=True)
            raise SystemExit(2) from err

    if args.display:
        display_bmp(bmp_path)
    else:
        LOGGER.info("BMP を %s に保存しました (display オプション無し)", bmp_path)


if __name__ == "__main__":
    main()
