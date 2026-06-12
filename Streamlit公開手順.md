# Streamlit公開手順

## 1. ローカルで動かす

`.streamlit/secrets.toml.example` を参考に、`.streamlit/secrets.toml` を作成する。

```toml
APP_PASSWORD = "任意の強いパスワード"
```

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

## 3. 注意点

このパスワード保護は、公開URLを知っている人に対して簡易的に閲覧制限するためのもの。
本格的な権限管理、ユーザー別ログイン、監査ログが必要な場合は、Streamlitの認証機能、SSO、社内ネットワーク配信などを検討する。

## 4. ファイル構成

- `streamlit_app.py`: Streamlit版シミュレーター本体
- `requirements.txt`: 公開環境に入れるPythonパッケージ
- `.streamlit/secrets.toml.example`: パスワード設定例
- `.gitignore`: 本物のSecretsをGitに入れないための設定
