# Picker2Paper

Picker2Paper は、Google Photos Picker やローカルファイルから取得した写真を AWS 上で加工し、Raspberry Pi + Waveshare e-Paper に画像を提供します。  
Web アップロード、画像変換パイプライン、デバイス側スクリプトを用途別に分割し、CDK と Python スクリプトで管理しています。

```text
picker2paper/
├─ cdk_photo_picker/     # Web アップロード UI + presign/manage API
├─ cdk_display_pipeline/ # 画像変換 + mTLS API (Raspberry Pi 向け)
└─ raspberryPi_code/     # e-paper デバイス用スクリプト
```

## コンポーネント

| ディレクトリ             | 役割 / 主な構成                                                                               | ドキュメント                                                |
|-------------------------|----------------------------------------------------------------------------------------------|-------------------------------------------------------------|
| `cdk_photo_picker/`     | Google ID トークン検証付きの Web アップロード環境。CloudFront + S3 + API Gateway + Lambda。 | `cdk_photo_picker/README.md`, `cdk_photo_picker/command.md` |
| `cdk_display_pipeline/` | 画像変換 Lambda、mTLS API、S3 CORS 設定、Route53 管理などバックエンド一式。                   | `cdk_display_pipeline/README.md`, `cdk_display_pipeline/command.md` |
| `raspberryPi_code/`     | Raspberry Pi が API から BMP を取得し、e-paper へ描画する Python ツール群。                 | `raspberryPi_code/README.md`                                |

各ディレクトリの README ではアーキテクチャや環境変数、デプロイ手順を詳しく説明しています。  
`\* /command.md` には日常的に使うセットアップ／`cdk synth`／`cdk diff`／`cdk deploy`／`pytest` コマンド例をまとめています。

## 全体フロー

1. `cdk_photo_picker` がホストする Web UI から Google Photos Picker もしくはローカルファイルを選択し、presigned URL 経由で S3 へアップロード。
2. `cdk_display_pipeline` が S3 イベントで Lambda を起動、画像を e-paper 用 BMP に変換しつつ Raspberry Pi 向けの mTLS API `/next-image` を公開。
3. `raspberryPi_code` の `fetch_next_image.py` などが定期的に API を呼び出し、取得した BMP を Waveshare e-Paper に描画。

## 共通要件

- AWS アカウントと CDK v2 環境（`npm install -g aws-cdk`）
- Python 3.11 以上
- Node.js / npm（CDK CLI 用）
- Raspberry Pi（例: Pi 4 Model B） + Waveshare 7.3inch ACeP 7-Color e-Paper
- 独自 CA など mTLS 用証明書を発行できる環境（OpenSSL など）

## 実装フロー

1. 目的のディレクトリに移動し、`.venv` 作成 → `pip install -r requirements.txt` → `cdk bootstrap`（アカウント/リージョンごとに一度）を実行。
2. `command.md` に沿って `pytest`, `cdk synth`, `cdk diff`, `cdk deploy` を順番に実施。
3. デプロイ後に出力される Endpoint / Bucket 名を `site/config.js` や Raspberry Pi 側設定へ反映。
4. Raspberry Pi 側は `raspberryPi_code/README.md` を参考にサービス化（`systemd` など）まで仕上げる。

設定値やコマンドの詳細は各ディレクトリ配下のドキュメントを参照してください。
