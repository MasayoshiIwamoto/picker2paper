```bash
# セットアップ（初回のみ）
cd picker2paper/cdk_photo_picker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap  # AWS アカウント + リージョンごとに 1 回

# Web アプリ設定
# site/config.js を編集し、Google clientId / presignEndpoint / manageEndpoint / s3KeyPrefix を指定

# デプロイ
cdk deploy PhotoPickerAppStack \
  --context domainName=photopicker.example.com \
  --context hostedZoneName=example.com \
  --context manageDns=true \
  --context siteBucketName=photopickerapp-site-ap-northeast-1-example \
  --context uploadsBucketName=photopickerapp-uploads-ap-northeast-1-example \
  --context uploadsPrefix=uploads/ \
  --context processedPrefix=processed/ \
  --context googleClientId=YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com \
  --context allowedEmailDomains="example.com" \
  --context allowedEmails="user@example.com" \
  --context cloudFrontCertificateArn=arn:aws:acm:us-east-1:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# テスト / 検証
pytest

# CloudFormation テンプレートの合成結果を確認
cdk synth PhotoPickerAppStack

# 既存スタックとの差分を確認
cdk diff PhotoPickerAppStack \
  --context domainName=photopicker.example.com \
  --context hostedZoneName=example.com \
  --context manageDns=true \
  --context siteBucketName=photopickerapp-site-ap-northeast-1-example \
  --context uploadsBucketName=photopickerapp-uploads-ap-northeast-1-example \
  --context uploadsPrefix=uploads/ \
  --context processedPrefix=processed/ \
  --context googleClientId=YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com \
  --context allowedEmailDomains="example.com" \
  --context allowedEmails="user@example.com" \
  --context cloudFrontCertificateArn=arn:aws:acm:us-east-1:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

- 既存バケットを Import する場合は `useExistingSiteBucket=true` / `useExistingUploadsBucket=true` を追加し、必要な CORS やポリシーを事前設定してください。
- `domainName` / `manageDns=true` を使う際は、us-east-1 の ACM 証明書を `cloudFrontCertificateArn` で指定するか、HostedZone 参照により `PhotoPickerCertStack` を同時デプロイしてください。
- `allowedEmailDomains` / `allowedEmails` はカンマ区切り。両方指定すると AND 条件になります。
- デプロイ後の `PresignEndpointForConfig` / `ManageEndpointForConfig` Output を `site/config.js` に反映します。
