# raspberryPi_code

Raspberry Pi 上で e-paper ディスプレイに写真を表示するための Python スクリプト群です。  
`cdk_display_pipeline` が提供する mTLS API (`/next-image`) を定期的に呼び出し、取得した BMP を Waveshare 7.3inch ACeP 7-Color e-Paper に描画します。

```
raspberryPi_code/
├─ fetch_next_image.py  # 画像取得 + 表示
└─ clear_display.py     # 画面初期化ユーティリティ
```

## 必要なもの

- Raspberry Pi (例: Raspberry Pi 4 Model B) + Raspberry Pi OS 64bit
- Waveshare 7.3inch ACeP 7-Color e-Paper (epd7in3f) と公式 Python ドライバ
- Python 3.11 以上、`pip install requests Pillow`
- `waveshare_epd` ドライバを `raspberryPi_code/lib/` に配置（[公式マニュアル](https://www.waveshare.com/wiki/7.3inch_e-Paper_HAT_(F)_Manual#Python) 参照）
- mTLS 用のクライアント証明書 (`device.crt`)、秘密鍵 (`device.key`)、信頼する CA (`myCA.pem`)

## セットアップ手順

1. **リポジトリ配置**
   ```bash
   git clone <this-repo> ~/picker2paper
   cd ~/picker2paper/raspberryPi_code
   ```
2. **Python 依存を導入**
   ```bash
   sudo apt update
   sudo apt install python3-pip python3-pil
   pip install requests Pillow
   ```
3. **waveshare_epd ドライバを配置**  
   Waveshare の GitHub もしくは提供物から `lib/waveshare_epd/` をこのディレクトリ直下にコピーします。
4. **証明書を配置**  
   `~/.ssh/myCA/` など任意の場所に `epaper-device.crt`, `epaper-device.key`, `myCA.pem` を保存し、権限を `chmod 600` で制限します。

## fetch_next_image.py

mTLS API から `bmp_url` を取得し、BMP をダウンロードして表示するスクリプトです。キャッシュ済みファイルは `.cache/` 下から再利用します。

```bash
python fetch_next_image.py \
  --api-url https://display.example.com/next-image \
  --cert /home/pi/.ssh/myCA/epaper-device.crt \
  --key  /home/pi/.ssh/myCA/epaper-device.key \
  --root-ca /home/pi/.ssh/myCA/myCA.pem \
  --save-dir /home/pi/display/pic \
  --display
```

- `--display` を省略するとダウンロードのみ行います。
- `--save-dir` 配下に `.cache/filename.bmp` が作成され、同名ファイルの再取得を避けます。
- API 応答に `object_key` が含まれない場合は `image-<timestamp>.bmp` が使われます。

### systemd で 30 分毎に実行する例

`/etc/systemd/system/fetch_next_image.service`

```ini
[Unit]
Description=Fetch next e-paper image and display
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/pi/picker2paper/raspberryPi_code
ExecStart=/usr/bin/python3 fetch_next_image.py \
  --api-url https://display.example.com/next-image \
  --cert /home/pi/.ssh/myCA/epaper-device.crt \
  --key  /home/pi/.ssh/myCA/epaper-device.key \
  --root-ca /home/pi/.ssh/myCA/myCA.pem \
  --save-dir /home/pi/display/pic \
  --display
Restart=on-failure
User=pi
```

`/etc/systemd/system/fetch_next_image.timer`

```ini
[Unit]
Description=Run fetch_next_image every 30 minutes between 6:00-23:00

[Timer]
OnCalendar=*-*-* 06..22:00:00
OnCalendar=*-*-* 06..22:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fetch_next_image.timer
```

## clear_display.py

e-paper の表示を単色で塗りつぶして初期化するユーティリティです。夜間や電源オフ前に画面をクリアしたい場合に利用します。

```bash
python clear_display.py --color black   # 他に red/yellow/orange などを選択可
```

`--verbose` を指定するとドライバのログを詳細に表示します。

## トラブルシューティング

- `waveshare_epd` が見つからない → `raspberryPi_code/lib/` に `waveshare_epd` ディレクトリをコピーし、SPI と I2C が有効化されているか確認してください。
- `requests` ImportError → `pip install requests` を再実行。
- mTLS で 403/495 → API 側の trust store (`cdk_display_pipeline` の `nextImageTruststoreUri`) に対応する CA か、証明書の有効期限を確認してください。
- 画像が更新されない → `.cache/` ディレクトリを削除するか、API 側で `object_key` がユニークになるよう設定してください。
