"""
TikTok Marketing API - OAuth2認証・Token管理
"""

import os
import time
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import yaml
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

TIKTOK_AUTH_URL = "https://business-api.tiktok.com/portal/auth"
TIKTOK_TOKEN_URL = "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/"
TIKTOK_REFRESH_URL = "https://business-api.tiktok.com/open_api/v1.3/oauth2/refresh_token/"

CONFIG_PATH = Path(__file__).parent.parent / "config" / "accounts.yaml"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """OAuthコールバックを受け取るローカルHTTPサーバー"""

    auth_code: Optional[str] = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "auth_code" in params:
            OAuthCallbackHandler.auth_code = params["auth_code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<html><body><h2>✅ 認証完了！このウィンドウを閉じてください。</h2></body></html>".encode("utf-8")
            )
            logger.success("OAuthコールバック受信: auth_code取得")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # サーバーログを抑制


class TikTokAuth:
    """TikTok Marketing API 認証管理クラス"""

    def __init__(self):
        self.app_id = os.getenv("TIKTOK_APP_ID")
        self.app_secret = os.getenv("TIKTOK_APP_SECRET")
        self.redirect_uri = os.getenv("TIKTOK_REDIRECT_URI", "https://aimforward.co.jp/")
        self.port = int(os.getenv("OAUTH_SERVER_PORT", "8080"))

        if not self.app_id or not self.app_secret:
            raise ValueError(".envにTIKTOK_APP_IDとTIKTOK_APP_SECRETを設定してください")

    # -------------------------------------------------------
    # OAuth2フロー
    # -------------------------------------------------------

    def get_auth_url(self, state: str = "tiktok_ads_tool") -> str:
        """認証URLを生成"""
        params = {
            "app_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "rid": "oauth2",
        }
        return f"{TIKTOK_AUTH_URL}?{urlencode(params)}"

    def run_oauth_flow(self, bc_name: str = "default") -> dict:
        """
        OAuthフローを実行してトークンを取得する
        ブラウザを自動で開き、認証後にトークンを保存
        """
        auth_url = self.get_auth_url()
        logger.info(f"ブラウザでTikTok認証ページを開きます...")
        logger.info(f"URL: {auth_url}")
        webbrowser.open(auth_url)

        # ローカルサーバーでコールバックを待機
        OAuthCallbackHandler.auth_code = None
        server = HTTPServer(("localhost", self.port), OAuthCallbackHandler)
        logger.info(f"コールバック待機中... (port: {self.port})")

        # タイムアウト付きでサーバーを起動
        server_thread = threading.Thread(target=server.handle_request)
        server_thread.start()
        server_thread.join(timeout=120)

        if not OAuthCallbackHandler.auth_code:
            raise TimeoutError("OAuth認証がタイムアウトしました（120秒）")

        # auth_code → access_token に交換
        token_data = self._exchange_code_for_token(OAuthCallbackHandler.auth_code)
        self._save_token(bc_name, token_data)

        logger.success(f"✅ [{bc_name}] 認証完了・トークン保存済み")
        return token_data

    def _exchange_code_for_token(self, auth_code: str) -> dict:
        """auth_code をアクセストークンに交換"""
        payload = {
            "app_id": self.app_id,
            "secret": self.app_secret,
            "auth_code": auth_code,
        }
        with httpx.Client() as client:
            resp = client.post(TIKTOK_TOKEN_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"トークン取得失敗: {data.get('message')}")

        token_info = data["data"]
        expires_at = datetime.now() + timedelta(seconds=token_info.get("expires_in", 86400))
        token_info["expires_at"] = expires_at.isoformat()
        return token_info

    def refresh_access_token(self, bc_name: str) -> dict:
        """リフレッシュトークンでアクセストークンを更新"""
        config = self._load_config()
        bc = self._find_bc(config, bc_name)

        if not bc.get("refresh_token"):
            raise ValueError(f"[{bc_name}] refresh_tokenがありません。再認証してください")

        payload = {
            "app_id": self.app_id,
            "secret": self.app_secret,
            "refresh_token": bc["refresh_token"],
        }
        with httpx.Client() as client:
            resp = client.post(TIKTOK_REFRESH_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"トークン更新失敗: {data.get('message')}")

        token_info = data["data"]
        expires_at = datetime.now() + timedelta(seconds=token_info.get("expires_in", 86400))
        token_info["expires_at"] = expires_at.isoformat()
        self._save_token(bc_name, token_info)

        logger.success(f"✅ [{bc_name}] アクセストークン更新完了")
        return token_info

    # -------------------------------------------------------
    # トークン取得（有効期限チェック付き）
    # -------------------------------------------------------

    def get_valid_token(self, bc_name: str) -> str:
        """
        有効なアクセストークンを返す
        期限切れの場合は自動でリフレッシュ
        """
        config = self._load_config()
        bc = self._find_bc(config, bc_name)

        if not bc.get("access_token"):
            raise ValueError(f"[{bc_name}] access_tokenがありません。run_oauth_flow()を実行してください")

        # 期限チェック（10分前にリフレッシュ）
        expires_at_str = bc.get("token_expires_at") or bc.get("expires_at", "")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.now() >= expires_at - timedelta(minutes=10):
                logger.info(f"[{bc_name}] トークン期限切れ間近 → 自動更新")
                token_data = self.refresh_access_token(bc_name)
                return token_data["access_token"]

        return bc["access_token"]

    # -------------------------------------------------------
    # 設定ファイル管理
    # -------------------------------------------------------

    def _load_config(self) -> dict:
        """accounts.yamlを読み込む"""
        if not CONFIG_PATH.exists():
            return {"business_centers": []}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"business_centers": []}

    def _save_config(self, config: dict):
        """accounts.yamlに書き込む"""
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    def _find_bc(self, config: dict, bc_name: str) -> dict:
        """BC名でビジネスセンター設定を検索"""
        for bc in config.get("business_centers", []):
            if bc.get("name") == bc_name:
                return bc
        raise ValueError(f"ビジネスセンター '{bc_name}' が見つかりません")

    def _save_token(self, bc_name: str, token_data: dict):
        """トークンをaccounts.yamlに保存"""
        config = self._load_config()
        bcs = config.setdefault("business_centers", [])

        # 既存のBCを探して更新、なければ追加
        target = None
        for bc in bcs:
            if bc.get("name") == bc_name:
                target = bc
                break

        if target is None:
            target = {"name": bc_name, "id": "", "ad_accounts": []}
            bcs.append(target)

        target["access_token"] = token_data.get("access_token", "")
        target["refresh_token"] = token_data.get("refresh_token", "")
        target["token_expires_at"] = token_data.get("expires_at", "")

        self._save_config(config)

    def add_business_center(self, bc_id: str, bc_name: str):
        """ビジネスセンターを設定ファイルに追加"""
        config = self._load_config()
        bcs = config.setdefault("business_centers", [])

        for bc in bcs:
            if bc.get("id") == bc_id:
                logger.warning(f"BC '{bc_name}' は既に登録済みです")
                return

        bcs.append({
            "id": bc_id,
            "name": bc_name,
            "access_token": "",
            "refresh_token": "",
            "token_expires_at": "",
            "ad_accounts": [],
        })
        self._save_config(config)
        logger.success(f"✅ ビジネスセンター追加: {bc_name} ({bc_id})")

    def list_business_centers(self) -> list:
        """登録済みビジネスセンター一覧を返す"""
        config = self._load_config()
        return config.get("business_centers", [])
