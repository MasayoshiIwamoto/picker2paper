# PhotoPicker Web Upload Stack

PhotoPicker Web Upload Stack は、Google Photos Picker API と Google Identity Services (GIS) を利用して選んだ写真やローカルファイルを Amazon S3 に安全にアップロードするための AWS CDK プロジェクトです。CloudFront + S3 でホスティングする静的 Web アプリと、S3 へのアップロードや一覧操作を行う API Gateway + Lambda をまとめてデプロイします。

## アプリの動作概要
- ブラウザから GIS でログインし、Photos Picker UI またはローカルファイル選択で画像を取得
- 取得した画像をブラウザが直接 S3 に PUT（presigned URL を Lambda が発行）
- `uploads/` 配下のアップロード済みオブジェクトを一覧表示し、必要に応じて削除
- `processed/` 配下にある電子ペーパー用 BMP などの変換済みオブジェクトが存在する場合は、同じ一覧から署名付き URL で閲覧

## リポジトリ構成
```text
picker2paper/cdk_photo_picker/
├─ app.py                    # CDK エントリーポイント（スタックの組み立て）
├─ cdk.json
├─ requirements.txt
├─ photo_picker/
│  ├─ app_stack.py           # Web + API + S3 一式
│  └─ cert_stack.py          # CloudFront 用 ACM 証明書（必要に応じてデプロイ）
├─ lambda/
│  ├─ presign/handler.py     # `/presign` — ID トークン検証 + S3 presigned URL 発行
│  └─ manage_uploads/handler.py  # `/uploads` — 一覧取得 / 削除 API
└─ site/
   ├─ index.html
   ├─ main.js
   ├─ styles.css
   └─ config.example.js
```

`site/` ディレクトリは同リポジトリ内に含まれます。`photo_picker/app_stack.py` の `BucketDeployment` が `../site` を参照するため、静的サイトのビルド成果物を同ディレクトリへ配置してください。

## 主なコンポーネント
- **CloudFront + S3 (OAC)**: 静的 Web アプリを TLS 必須で配信。S3 バケットは非公開で、CloudFront の Origin Access Control のみを許可します。
- **API Gateway + Lambda**: `/presign` と `/uploads` エンドポイントを提供。認証は Google ID トークンの検証で行います。
- **`lambda/presign`**: `POST /presign` に対して署名付き PUT URL を返却。`allowedEmailDomains` / `allowedEmails` でアクセス制御。
- **`lambda/manage_uploads`**: `GET /uploads` でページング付きの一覧を返し、`DELETE /uploads` でオリジナルと派生ファイルを削除。
- **Site (`main.js`)**:
  - GIS/FedCM を利用したサインインとトークン更新
  - Photos Picker セッションの作成、完了ポーリング、メディア取得
  - presigned URL を使った PUT / multipart POST 両対応のアップロード
  - アップロード進捗表示、ローカルファイル取り込み、uploads API との連携表示・削除

## 前提条件
1. **AWS アカウント**
   - `ap-northeast-1` などデプロイ対象リージョンで CDK が実行できること。
   - 初回は `cdk bootstrap` が必要です（デフォルトで実行するリージョンに合わせる）。
2. **ドメイン & 証明書（任意）**
   - カスタムドメインを利用する場合は、Route 53 Hosted Zone かつ us-east-1 の ACM 証明書が必要です。
   - 証明書 ARN を指定しない場合でも、`domainName` と `hostedZoneName` を与えると `PhotoPickerCertStack` が us-east-1 に DNS 検証付き証明書を発行します。
3. **Google Cloud プロジェクト**
   - Google Photos Picker API を有効化し、Web アプリ用 OAuth クライアント ID を発行します。
   - OAuth 同意画面で `https://www.googleapis.com/auth/photospicker.mediaitems.readonly` スコープを追加し、テストユーザーを登録します（公開前は必須）。

## セットアップ
```bash
cd picker2paper/cdk_photo_picker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# アカウント/リージョンごとに初回だけ実行
cdk bootstrap
```

## Google Cloud 設定手順（概要）
1. Google Cloud コンソールで新規プロジェクトを作成。
2. 「API とサービス」>「ライブラリ」から **Google Photos Picker API** を有効化。
3. OAuth 同意画面でアプリ情報と承認済みドメインを登録し、`https://www.googleapis.com/auth/photospicker.mediaitems.readonly` を追加。
4. 「認証情報」>「認証情報を作成」>「OAuth クライアント ID」から種別「ウェブアプリケーション」を選択し、承認済み JavaScript 生成元に Web アプリのドメインを登録。
5. 発行したクライアント ID を `site/config.js` の `google.clientId` に設定。

本プロジェクトのフロントエンドは FedCM 対応済みで、ポップアップがブロックされる環境ではオーバーレイで再サインインを促します。

## CDK コンテキスト一覧
| コンテキストキー | 必須 | 説明 |
| --- | --- | --- |
| `domainName` | 任意 | CloudFront に割り当てるカスタムドメイン。指定した場合は `cloudFrontCertificateArn` も必要。 |
| `hostedZoneName` | 任意 | `manageDns=true` や 証明書自動発行時に参照する Route 53 Hosted Zone。末尾のドットは不要。 |
| `cloudFrontCertificateArn` | 任意 | us-east-1 の ACM 証明書 ARN。未指定で `domainName`/`hostedZoneName` がある場合は `PhotoPickerCertStack` が作成。 |
| `manageDns` (`enableDns`) | 任意 | `true` の場合、Route 53 に CloudFront エイリアスレコードを自動作成。 |
| `disableDns` | 任意 | 旧互換。`true` なら Route 53 レコード作成を抑止。`manageDns` が優先。 |
| `siteBucketName` | 任意 | 静的サイト用 S3 バケット名。省略すると CDK が一意な名前を付与。 |
| `uploadsBucketName` | 任意 | アップロード用 S3 バケット名。省略時は自動生成。 |
| `useExistingSiteBucket` | 任意 | `true` の場合は既存バケットを import（削除ポリシーや OAC 用ポリシーは付与されません）。 |
| `useExistingUploadsBucket` | 任意 | 同上。 |
| `uploadsPrefix` | 任意 | アップロード格納プレフィックス（デフォルト `uploads/`）。 |
| `processedPrefix` | 任意 | 変換済みファイルのプレフィックス（デフォルト `processed/`）。 |
| `googleClientId` | 任意 | サーバ側で ID トークン検証時に利用するクライアント ID。設定推奨。 |
| `allowedEmailDomains` | 任意 | カンマ区切りのドメイン許可リスト。 |
| `allowedEmails` | 任意 | カンマ区切りのメールアドレス許可リスト。ドメイン指定と併用すると AND 条件になります。 |

## デプロイ例
```bash
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
```

- `uploadsBucketName` を省略すると `PhotoPickerAppStack-UploadsBucketXXXXXXXX` のような一意名が割り当てられます。
- 既存バケットを使う場合は `useExistingSiteBucket=true` / `useExistingUploadsBucket=true` を併用し、ポリシー・CORS 設定を手動で整備します。
- `manageDns=true` を指定する際は `domainName`、`hostedZoneName`、`cloudFrontCertificateArn`（または自動発行用の Hosted Zone）が必須です。
- `allowedEmailDomains` / `allowedEmails` を併用すると両条件を満たしたユーザーのみ API を利用できます。

## デプロイ後の主な Outputs
- `SiteBucketName` — 静的サイトを配置する S3 バケット名
- `UploadsBucketName` — アップロード用 S3 バケット名
- `DistributionDomainName` — CloudFront の自動割り当てドメイン
- `PresignEndpointForConfig` — `site/config.js` の `upload.presignEndpoint` として設定する URL
- `ManageEndpointForConfig` — `site/config.js` の `upload.manageEndpoint` として設定する URL
- `SiteDnsRecord` — `manageDns=false` の場合に表示。Route 53 へ手動登録するエイリアスレコードの案内

## Web アプリ設定 (`site/config.js`)
`config.example.js` を `config.js` にコピーし、以下を編集します。

```js
window.AppConfig = {
  google: {
    clientId: "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com",
    scopes: ["https://www.googleapis.com/auth/photospicker.mediaitems.readonly"],
  },
  upload: {
    presignEndpoint: "https://<api-id>.execute-api.ap-northeast-1.amazonaws.com/prod/presign",
    manageEndpoint: "https://<api-id>.execute-api.ap-northeast-1.amazonaws.com/prod/uploads",
    s3KeyPrefix: "uploads/"
  }
};
```

- `presignEndpoint` は `POST /presign` に向けます。
- `manageEndpoint` を設定するとアップロード済み一覧・削除 UI が動作します。
- `s3KeyPrefix` を変更した場合は CDK コンテキストの `uploadsPrefix` と一致させてください。
- 設定を変更したら `cdk deploy` で再デプロイし、CloudFront のキャッシュも自動で無効化されます。

## API エンドポイント仕様
- **`POST /presign`**  
  - リクエストボディ: `{"key": "uploads/filename.jpg", "contentType": "image/jpeg"}`  
  - `Authorization: Bearer <Google ID Token>` ヘッダー必須。  
  - レスポンス: `{"url": "https://s3..."}`（PUT 用 URL）。将来的な互換のため `main.js` は `{url, fields}` 形式にも対応しています。
- **`GET /uploads`**  
  - クエリ: `limit`（既定 10, 最大 200）、`offset`。  
  - レスポンスには `items`, `count`, `total`, `nextOffset`, `hasMore` を含みます。各アイテムには `processedUrl` や `processedKey` が付与される場合があります。
- **`DELETE /uploads`**  
  - リクエストボディ: `{"key": "uploads/filename.jpg"}`。  
  - 指定キーのオブジェクトを削除し、対応する `processedPrefix` の派生ファイル（例: `.bmp`）も削除します。

いずれのエンドポイントも CORS ヘッダーで `Authorization`, `Content-Type`, `x-device-token` を許可しており、ブラウザから直接呼び出せます。

## Lambda 実装メモ
- `lambda/presign`
  - Google ID トークンは `https://oauth2.googleapis.com/tokeninfo` で検証します。
  - バケット権限は `s3:PutObject` のみ必要。レスポンスは 15 分間有効な presigned PUT URL。
- `lambda/manage_uploads`
  - `list_objects_v2` で `uploadsPrefix` と `processedPrefix` をスキャンし、最新順に並べ替えて返却。
  - `DELETE` 時はアップロード元キーに対応する `processed/xxxx.bmp` も削除対象とし、失敗した場合はレスポンスに `warning` を含めます。
  - `MAX_ITEMS`（デフォルト 200）で 1 回の取得件数を制限しています。

## デプロイ時の注意
- CloudFront から S3 へアクセスするため、バケットは自動で OAC とバケットポリシーが設定されます。既存バケットをインポートする場合は手動設定が必要です。
- Lambda から外部 HTTPS へアクセス（Google tokeninfo）するため、VPC に閉じる場合は NAT などを用意してください。
- `uploads` バケットには CORS (`PUT`, `POST`, `ETag` 露出) が自動付与されます。ドメイン変更時は再デプロイで更新されます。

## トラブルシューティング
- **Photos Picker のポップアップが開かない**: ブラウザ側のポップアップブロックを解除するか、オーバーレイ内のサインイン操作を先に実行してください。
- **APIから 401 が返る**: `site/config.js` の `google.clientId` と CDK コンテキストの `googleClientId` が一致しているか、または `allowedEmailDomains`/`allowedEmails` で拒否されていないか確認します。
- **一覧が空のまま**: `upload.manageEndpoint` を設定し忘れていないか、`uploadsPrefix` が実際のキーと一致しているか確認します。
