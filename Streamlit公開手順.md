# Streamlit公開手順

## 1. ローカルで動かす

`.streamlit/secrets.toml.example` を参考に、`.streamlit/secrets.toml` を作成する。

```toml
APP_PASSWORD = "任意の強いパスワード"
```

Google Drive連携を使う場合は、同じ `secrets.toml` にDrive用の設定も追加する。

```toml
GOOGLE_DRIVE_FOLDER_ID = "Google Driveの保存先フォルダID"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
universe_domain = "googleapis.com"
```

`private_key` の中身は、Google Cloudから取得したJSON内では `\n` が入っている。
Secretsに貼り付けるときも、実際の改行に変換せず `\n` のまま残す。

依存関係を入れて起動する。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/streamlit run streamlit_app.py
```

## 2. Streamlit Community Cloudで公開する

1. このフォルダの内容をGitHubリポジトリに置く
2. Streamlit Community Cloudで新規アプリを作る
3. Main file pathに `streamlit_app.py` を指定する
4. App settingsのSecretsに以下を設定する

```toml
APP_PASSWORD = "任意の強いパスワード"
```

5. 発行されたURLを共有する

## 3. Google Drive保存を使う

GitHub Public repoには、事業計画データのJSONを置かない。
入力データはGoogle Driveの限定フォルダに保存し、アプリはSecrets経由でそのフォルダにアクセスする。
Google Drive連携を設定すると、アプリ起動時にDrive上の最新JSONを一度だけ自動で読み込む。

設定手順:

1. Google Cloudで新規プロジェクト、または既存プロジェクトを開く
2. Google Drive APIを有効化する
3. サービスアカウントを作成する
4. サービスアカウントのJSONキーを発行する
5. Google Driveの `Shared Drive` に保存先フォルダを作る
6. Shared Drive または保存先フォルダをサービスアカウントの `client_email` に共有する
7. フォルダURLの `/folders/` 以降を `GOOGLE_DRIVE_FOLDER_ID` に設定する
8. サービスアカウントJSONの各項目を `[gcp_service_account]` に設定する

Streamlit Community Cloudでは、アプリのSettingsからSecretsを開き、上記のTOMLを貼り付ける。
ローカルでは `.streamlit/secrets.toml` に同じ内容を書く。

よくあるエラー:

`json.decoder.JSONDecodeError: Invalid control character` が出る場合は、サービスアカウントJSONの `private_key` に本物の改行が入っている可能性が高い。
`private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"` のように、改行を `\n` のまま書く。

`Service Accounts do not have storage quota` が出る場合は、保存先フォルダが `マイドライブ` 上にある。
サービスアカウントは `マイドライブ` に新規保存できないため、保存先を `Shared Drive` に移す。

## 4. 固定費計画を使う

初期状態では、今期実績の固定費を年換算して必要売上高を逆算する。
来期の固定費計画を使う場合は、サイドバーの `固定費計画を使う` をONにする。

入力タブの `固定費計画(年額)` に、来期の事業部別・共通部門別の固定費計画を入力する。
既存データをもとに始める場合は、`固定費計画に今期年換算を反映` ボタンで、今期年換算固定費を初期値として入れられる。

## 5. 月次予算を使う

`月次予算` タブでは、勘定科目を自由に追加し、各科目の `PL区分` と `固変区分` を設定する。
売上原価は変動費、売上は売上区分として扱う。

月次予算の入力単位は `事業部・共通部門 × 勘定科目 × 月`。
入力した月次予算は、年額集計と月次P/Lとして確認できる。

`月次予算をシミュレーション入力へ反映` を押すと、月次予算の年額を入力タブの `売上 / 売上原価 / 販管費(変動) / 販管費(固定)` に反映する。
このとき、実績月数は `12`、固定費計画はONになる。

JSON保存には、勘定科目マスタと月次予算明細も含まれる。
CSVでは、結果CSVとは別に月次予算CSVを保存できる。

## 6. 注意点

このパスワード保護は、公開URLを知っている人に対して簡易的に閲覧制限するためのもの。
本格的な権限管理、ユーザー別ログイン、監査ログが必要な場合は、Streamlitの認証機能、SSO、社内ネットワーク配信などを検討する。

Google Drive連携を使う場合でも、アプリのパスワードを知っている人はDrive上の保存済みJSONをアプリ経由で読める。
本格的なユーザー別権限管理が必要な場合は、Googleアカウントログインや社内SSOの利用を検討する。

## 7. ファイル構成

- `streamlit_app.py`: Streamlit版シミュレーター本体
- `requirements.txt`: 公開環境に入れるPythonパッケージ
- `.streamlit/secrets.toml.example`: パスワード設定例
- `.gitignore`: 本物のSecretsをGitに入れないための設定
