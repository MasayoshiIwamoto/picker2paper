```bash
# 初回のみ: CDK 用ブートストラップ
cd picker2paper/cdk_display_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap

# デプロイ
cdk deploy DisplayPipelineStack \
  --context uploadsBucketName=display-pipeline-uploads-ap-northeast-1-example \
  --context uploadsPrefix=uploads/ \
  --context processedPrefix=processed/ \
  --context displayStateKey=state/.display_state.json \
  --context presignedTtlSeconds=120 \
  --context nextImageDomainName=display.example.com \
  --context nextImageCertificateArn=arn:aws:acm:ap-northeast-1:123456789012:certificate/xxxxxxxx \
  --context nextImageTruststoreUri=s3://trust-store-example/myCA.pem \
  --context nextImageStageName=prod \
  --context hostedZoneName=example.com \
  --context manageDns=true  # Route 53 の alias レコードも自動作成したい場合のみ
```

- `uploadsBucketName` を省略すると CloudFormation が `DisplayPipelineStack-UploadsBucketXXXXXXXX` のような一意のバケット名を自動割り当てします。固定したい場合は `--context uploadsBucketName=...` で指定してください。
- `nextImageDomainName` には ACM 証明書と truststore に対応するカスタムドメインを指定してください (mTLS)。
- `manageDns=true` を付ける場合は、同時に `--context hostedZoneName=example.com` のように対象の Route 53 ゾーン名も指定してください。省略すると DNS レコードは作成されません。`nextImageDomainName` は `hostedZoneName` と一致するか、配下のサブドメインである必要があります。
- `manageDns=true` を付けない場合、Route 53 のレコードは自動作成しません。デプロイ後に出力される alias ターゲットを使って手動で登録します。

# テスト / 検証
```bash
# 1. 依存インストール（未実施の場合）
cd picker2paper/cdk_display_pipeline
pip install -r requirements.txt
pytest

# 2. CDK テンプレートの合成確認
cdk synth

# 3. 既存スタックとの差分確認（未デプロイなら --no-previous-parameters 推奨）
cdk diff DisplayPipelineStack \
  --context uploadsBucketName=display-pipeline-uploads-ap-northeast-1-example \
  --context uploadsPrefix=uploads/ \
  --context processedPrefix=processed/ \
  --context displayStateKey=state/.display_state.json \
  --context presignedTtlSeconds=120 \
  --context nextImageDomainName=display.example.com \
  --context nextImageCertificateArn=arn:aws:acm:ap-northeast-1:123456789012:certificate/xxxxxxxx \
  --context nextImageTruststoreUri=s3://trust-store-example/myCA.pem \
  --context nextImageStageName=prod \
  --context hostedZoneName=example.com \
  --context manageDns=true

# 4. 実際に検証できる環境がある場合のみデプロイ（IAM / Route53 / ACM 設定済み前提）
cdk deploy DisplayPipelineStack \
  --require-approval never \
  --context uploadsBucketName=display-pipeline-uploads-ap-northeast-1-example \
  --context uploadsPrefix=uploads/ \
  --context processedPrefix=processed/ \
  --context displayStateKey=state/.display_state.json \
  --context presignedTtlSeconds=120 \
  --context nextImageDomainName=display.example.com \
  --context nextImageCertificateArn=arn:aws:acm:ap-northeast-1:123456789012:certificate/xxxxxxxx \
  --context nextImageTruststoreUri=s3://trust-store-example/myCA.pem \
  --context nextImageStageName=prod \
  --context hostedZoneName=example.com \
  --context manageDns=true
```
