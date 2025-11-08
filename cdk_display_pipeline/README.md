# Display Pipeline Stack (e-paper delivery)

このディレクトリには、S3 に置いた画像を e-paper 向けに変換し、mTLS 付き API で Raspberry Pi へ配信する最小構成の CDK プロジェクトが含まれています。

- S3 バケット (1 つ) : オリジナル画像を `uploads/` に配置
- S3 イベント → Lambda `format_image` : 800×480 BMP に変換して `processed/` に保存
- API Gateway `/next-image` → Lambda `get_next_image` : 表示履歴 (`state/.display_state.json`) を参照しつつ署名付き URL を返却

## デプロイ手順

```bash
cd picker2paper/cdk_display_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cdk bootstrap   # cdk初回実行時のみ

# デプロイ
cdk deploy DisplayPipelineStack \
  --context uploadsBucketName=photo-picker-uploads-ap-northeast-1-example \
  --context uploadsPrefix=uploads/ \
  --context processedPrefix=processed/ \
  --context displayStateKey=state/.display_state.json \
  --context presignedTtlSeconds=120 \
  --context nextImageDomainName=display.example.com \
  --context nextImageCertificateArn=arn:aws:acm:ap-northeast-1:xxxxxxxxxx:certificate/xxxxxxxx \
  --context nextImageTruststoreUri=s3://trust-store-example/myCA.pem \
  --context nextImageStageName=prod \
  --context hostedZoneName=example.com \
  --context manageDns=true
```

## 主な context
`nextImageDomainName` / `nextImageCertificateArn` / `nextImageTruststoreUri` などの context を指定してください。
- `uploadsBucketName` を省略すると CloudFormation が `DisplayPipelineStack-UploadsBucketXXXXXXXX` のような一意のバケット名を自動で割り当てます。固定したい場合は `--context uploadsBucketName=...` で指定してください。
- Route 53 のレコードはデフォルトで自動作成しません。CDK に管理させたい場合のみ `--context manageDns=true` と、対象ゾーン名を指す `--context hostedZoneName=example.com` を併せて指定してください。`nextImageDomainName` は `hostedZoneName` と一致するか、その配下のサブドメインである必要があります。
  - 付けない場合はデプロイ後の `SiteDnsRecord` / `NextImageManualDnsRecord` 出力を参考に手動で alias A レコードを登録します。
- `nextImageTruststoreUri` は事前作業で作成し、S3にアップロードしたルートCA証明書のURIを指定します。
- `pytest` を実行すると CDK の synth/diff 相当の検証とスタックアサーションがまとめて行えます（`picker2paper/cdk_display_pipeline/tests/` を参照）。


## デプロイ後に確認できる Outputs

- `ManualUploadBucketName` / `ProcessedBucketName`
- `NextImageMtlsEndpoint` : mTLS を有効化したカスタムドメイン（指定時のみ）
- `NextImageManualDnsRecord` : DNS を手動登録する際の案内
- `UploadsPrefix` / `ProcessedPrefix` : 利用中の S3 プレフィックス

> RestApi は `disable_execute_api_endpoint=True` で作成しているため、execute-api ドメインは公開されません。

## 処理の流れ

1. `UploadsBucketName` の `uploads/` に JPEG/PNG などをアップロード。
2. S3 イベントで `lambda/format_image` が起動し、BMP を `processed/` に生成。
3. Raspberry Pi が `https://<NextImageMtlsEndpoint>` を呼び出すと、次に表示すべき BMP の署名付き URL が返る。
4. `raspberryPi_code/fetch_next_image.py` 等でダウンロードし、e-paper に描画。

## 構成ファイル

- `display_pipeline/app_stack.py` : CDK スタック本体
- `lambda/format_image/` : 画像変換 Lambda (Pillow)
- `lambda/get_next_image/` : 次に表示する BMP を抽選する Lambda

Qiita 記事に合わせて必要最小限のリソースを定義しており、Web アプリ側 (アップロード UI) は `picker2paper/cdk_photo_picker` に分離しています。
