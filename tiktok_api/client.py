"""
TikTok Marketing API - HTTPクライアント基盤
レート制限・リトライ・エラーハンドリングを統括
"""

import time
from typing import Any, Optional

import httpx
from loguru import logger

BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"

# レート制限設定
RATE_LIMIT_REQUESTS = 15       # 最大リクエスト数
RATE_LIMIT_WINDOW = 1.0        # 秒単位のウィンドウ
MAX_RETRIES = 3                # 最大リトライ回数
RETRY_WAIT = 2.0               # リトライ間隔（秒）


class TikTokAPIError(Exception):
    """TikTok APIエラー基底クラス"""
    def __init__(self, code: int, message: str, request_id: str = ""):
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"[{code}] {message} (request_id: {request_id})")


class RateLimiter:
    """シンプルなレート制限管理"""

    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS, window: float = RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window = window
        self._timestamps: list[float] = []

    def wait_if_needed(self):
        """必要ならウェイト"""
        now = time.time()
        # ウィンドウ外のタイムスタンプを削除
        self._timestamps = [t for t in self._timestamps if now - t < self.window]

        if len(self._timestamps) >= self.max_requests:
            wait_time = self.window - (now - self._timestamps[0])
            if wait_time > 0:
                logger.debug(f"レート制限: {wait_time:.2f}秒待機")
                time.sleep(wait_time)

        self._timestamps.append(time.time())


class TikTokClient:
    """TikTok Marketing API HTTPクライアント"""

    def __init__(self, access_token: str, advertiser_id: str = ""):
        self.access_token = access_token
        self.advertiser_id = advertiser_id
        self._rate_limiter = RateLimiter()
        self._http = httpx.Client(
            base_url=BASE_URL,
            timeout=30.0,
            headers={
                "Access-Token": access_token,
                "Content-Type": "application/json",
            },
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._http.close()

    def close(self):
        self._http.close()

    # -------------------------------------------------------
    # 基本HTTPメソッド
    # -------------------------------------------------------

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        """GETリクエスト"""
        return self._request("GET", path, params=params)

    def post(self, path: str, body: Optional[dict] = None) -> dict:
        """POSTリクエスト"""
        return self._request("POST", path, body=body)

    def _request(self, method: str, path: str, params: Optional[dict] = None, body: Optional[dict] = None) -> dict:
        """リトライ付きリクエスト実行"""
        self._rate_limiter.wait_if_needed()

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if method == "GET":
                    resp = self._http.get(path, params=params)
                else:
                    resp = self._http.post(path, json=body)

                resp.raise_for_status()
                data = resp.json()

                # TikTok APIレスポンスコードチェック
                code = data.get("code", -1)
                if code == 0:
                    return data.get("data", data)
                elif code == 40100:
                    raise TikTokAPIError(code, "アクセストークンが無効です", data.get("request_id", ""))
                elif code == 40101:
                    raise TikTokAPIError(code, "アクセストークンの期限切れです", data.get("request_id", ""))
                elif code == 50002:
                    # レート制限 → リトライ
                    wait = RETRY_WAIT * attempt
                    logger.warning(f"レート制限 (attempt {attempt}/{MAX_RETRIES}) → {wait}秒待機")
                    time.sleep(wait)
                    continue
                else:
                    raise TikTokAPIError(code, data.get("message", "不明なエラー"), data.get("request_id", ""))

            except httpx.HTTPStatusError as e:
                if attempt < MAX_RETRIES:
                    logger.warning(f"HTTPエラー {e.response.status_code} (attempt {attempt}/{MAX_RETRIES}) → リトライ")
                    time.sleep(RETRY_WAIT * attempt)
                else:
                    raise

            except httpx.RequestError as e:
                if attempt < MAX_RETRIES:
                    logger.warning(f"接続エラー (attempt {attempt}/{MAX_RETRIES}): {e} → リトライ")
                    time.sleep(RETRY_WAIT * attempt)
                else:
                    raise

        raise TikTokAPIError(-1, f"最大リトライ回数({MAX_RETRIES})を超えました")

    # -------------------------------------------------------
    # ページング対応リスト取得
    # -------------------------------------------------------

    def get_all(self, path: str, params: Optional[dict] = None, page_size: int = 100) -> list:
        """ページングを自動処理して全件取得"""
        all_items = []
        page = 1
        params = params or {}
        params["page_size"] = page_size

        while True:
            params["page"] = page
            data = self.get(path, params=params)

            items = data.get("list", [])
            all_items.extend(items)

            page_info = data.get("page_info", {})
            total_page = page_info.get("total_page", 1)

            logger.debug(f"ページ {page}/{total_page} 取得 ({len(items)}件)")

            if page >= total_page:
                break
            page += 1

        logger.debug(f"合計 {len(all_items)} 件取得")
        return all_items
