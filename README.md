# Photo Display Pipeline

Raspberry Pi と Waveshare 7.3inch e-Paper を組み合わせて写真スライドショーを表示するためのコード一式です。AWS 上のインフラは用途ごとに CDK プロジェクトを分割しています。

```text
picker2paper/
├─ cdk_photo_picker/     # Web アップロード UI + presign/manage API (PhotoPicker Web Upload Stack)
├─ cdk_display_pipeline/ # 画像変換 + e-paper 配信用 API (Display Pipeline Stack)
└─ raspberryPi_code/     # Raspberry Pi 用 Python スクリプト
```

## 共通の前提

- AWS アカウント
- Node.js / npm（AWS CDK CLI 用）
- Python 3.11 以上
- AWS CDK v2 (`npm install -g aws-cdk`)
- Raspberry Pi（例: Raspberry Pi 4 Model B 4GB）
- Waveshare 7.3inch ACeP 7-Color e-Paper HAT
- mTLS 用のカスタム CA 証明書を発行できる環境（OpenSSL など）

---

## Web アップロード側 (cdk_photo_picker/)

Google OAuth で認証したユーザがブラウザから S3 に写真をアップロードし、アップロード済み画像を参照・削除できるスタックです。

- CloudFront + S3 (静的サイト `site/`)
- Lambda (`presign`, `manage_uploads`) + API Gateway `/presign`, `/uploads`
- Google ID トークン検証とメールドメイン / 個別メールの制御

セットアップやデプロイ手順は `picker2paper/cdk_photo_picker/README.md` を参照してください。

---

## e-paper 配信側 (cdk_display_pipeline/)

アップロード済み画像を e-paper 向け BMP へ変換し、mTLS 付き API で Raspberry Pi に配信するスタックです。

### 事前準備

- (任意) Amazon Route 53 で API 用ドメインのホストゾーンを用意します。既存 DNS を使う場合は、後述の Outputs を参考に手動でレコードを追加します。
- AWS Certificate Manager (ap-northeast-1) で `display.example.com` など API Gateway 向けの証明書を発行します。ワイルドカード証明書でも構いません。
- mTLS 用のルート CA 証明書を作成し、API Gateway が参照できるよう信頼ストアを S3 に配置します。以下は一例です。

```bash
SUFFIX="example"
BUCKET="trust-store-${SUFFIX}"
OBJECT_KEY="myCA.pem"
KEY_PATH="$HOME/.ssh/myCA/myCA.pem"

aws s3 mb "s3://${BUCKET}/"

aws s3api put-bucket-policy \
  --bucket "${BUCKET}" \
  --policy "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [
      {
        \"Sid\": \"AllowApiGatewayToReadTruststore\",
        \"Effect\": \"Allow\",
        \"Principal\": {\"Service\": \"apigateway.amazonaws.com\"},
        \"Action\": [\"s3:GetObject\", \"s3:GetObjectVersion\"],
        \"Resource\": \"arn:aws:s3:::${BUCKET}/${OBJECT_KEY}\"
      }
    ]
  }"

aws s3 cp "${KEY_PATH}" "s3://${BUCKET}/${OBJECT_KEY}"
```

### セットアップ

```bash
cd picker2paper/cdk_display_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 初回のみ
cdk bootstrap
```

### デプロイ例

```bash
cdk deploy DisplayPipelineStack \
  --context uploadsBucketName=display-pipeline-uploads-example \
  --context uploadsPrefix=uploads/ \
  --context processedPrefix=processed/ \
  --context displayStateKey=state/.display_state.json \
  --context presignedTtlSeconds=120 \
  --context nextImageDomainName=display.example.com \
  --context nextImageCertificateArn=arn:aws:acm:ap-northeast-1:123456789012:certificate/xxxxxxxx \
  --context nextImageTruststoreUri=s3://trust-store-example/myCA.pem \
  --context nextImageStageName=prod \
  --context hostedZoneName=example.com
```

- `uploadsBucketName` を省略すると CloudFormation が `DisplayPipelineStack-UploadsBucketXXXXXXXX` のような一意のバケット名を割り当てます。固定したい場合のみ明示してください。
- `nextImageDomainName` / `nextImageCertificateArn` / `nextImageTruststoreUri` はセットで指定します。S3 に置いた信頼ストアの URI (`s3://bucket/key`) を `nextImageTruststoreUri` に渡すと mTLS カスタムドメインが有効化されます。
- `nextImageStageName` は API Gateway のステージを変更したい場合に利用します (既定値: `prod`)。
- `displayStateKey` で Lambda が表示履歴を保存する S3 キーを変更できます。
- `presignedTtlSeconds` は署名付き URL の有効期限 (秒) を調整します。
- Route 53 で DNS を管理する場合は `--context manageDns=true --context hostedZoneName=example.com` を追加すると、スタックが A レコード (ALIAS) を作成します。省略時は Outputs (`NextImageManualDnsRecord`) を参考に手動登録します。
- `pytest` を実行すると CDK の synth/diff 相当の検証とスタックアサーションがまとめて行えます。

### デプロイ後に確認できる Outputs

- `ManualUploadBucketName` : 手動アップロードに利用する S3 バケット。`uploadsPrefix` がプレフィックスです。
- `ProcessedBucketName` : 変換済み BMP が保存される同一バケット。`processedPrefix` を参照します。
- `NextImageMtlsEndpoint` : mTLS カスタムドメインを構成した場合に表示される API エンドポイント。
- `NextImageManualDnsRecord` : DNS を手動で管理するときに作成すべき alias A レコードの案内。

> 備考: RestApi は `disable_execute_api_endpoint=True` で作成しているため、execute-api ドメインは公開されません。mTLS カスタムドメイン経由でのみアクセスできます。

### 動作の流れ

1. `ManualUploadBucketName` 内の `uploadsPrefix`（既定: `uploads/`）に JPEG / PNG / HEIC などをアップロード。
2. S3 イベントで Lambda `format_image` が起動し、800×480 BMP を `processed/` に生成。
3. Raspberry Pi が API Gateway `/next-image`（mTLS）を呼び出し、次に表示すべき BMP の署名付き URL を取得。
4. 取得した BMP を e-paper に描画。

---

## Raspberry Pi 側 (raspberryPi_code/)

1. Raspberry Pi OS (64bit) をインストールし、SSH・Wi-Fi を有効化。
2. Waveshare 公式ドキュメント「Working With Raspberry Pi > Python」に従って SPI を有効化し、`waveshare_epd` ドライバを `raspberryPi_code/lib/` に配置。
3. `pip install requests Pillow` で依存を導入。
4. `epaper-device.crt` / `epaper-device.key` / `myCA.pem` を設置し、権限を調整。

### 画像取得と描画

```bash
python raspberryPi_code/fetch_next_image.py \
  --api-url https://display.example.com/next-image \
  --cert /home/pi/.ssh/myCA/epaper-device.crt \
  --key  /home/pi/.ssh/myCA/epaper-device.key \
  --root-ca /home/pi/.ssh/myCA/myCA.pem \
  --save-dir /home/pi/display/pic \
  --display
```

### systemd 例

`/etc/systemd/system/fetch_next_image.service`

```ini
[Unit]
Description=Fetch next display image and render on e-paper
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/pi/picker2paper/raspberryPi_code/fetch_next_image.py --api-url https://display.example.com/next-image --cert /home/pi/.ssh/myCA/epaper-device.crt --key /home/pi/.ssh/myCA/epaper-device.key --save-dir /home/pi/display/pic --display
WorkingDirectory=/home/pi/picker2paper/raspberryPi_code
StandardOutput=journal
StandardError=journal
Restart=on-failure
User=pi
```

`/etc/systemd/system/fetch_next_image.timer`

```ini
[Unit]
Description=Run fetch_next_image.service every 30 min between 6:00 and 23:00

[Timer]
OnCalendar=*-*-* 06..22:00:00
OnCalendar=*-*-* 06..22:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now fetch_next_image.timer
```

夜間は `python raspberryPi_code/clear_display.py --color white` をタイマーで実行し、表示をリセットできます。
