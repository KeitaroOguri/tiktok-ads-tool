"""
Google Drive動画 → TikTokクリエイティブライブラリ アップローダー

【使い方】
1. Google DriveのファイルをサービスアカウントのEmailと共有する
   (tiktok-ads-tool@winged-vigil-371710.iam.gserviceaccount.com)
2. スプレッドシートの「Google Drive動画URL」列にURLを貼り付ける
3. ツールが自動でダウンロード → TikTokにアップロード → video_idを取得する
"""

from __future__ import annotations
import os
import re
import tempfile
from pathlib import Path
from loguru import logger
import httpx


# -------------------------------------------------------
# URL からファイルIDを抽出
# -------------------------------------------------------

def extract_drive_file_id(url: str) -> str:
    """
    Google Drive共有URLからファイルIDを抽出する

    対応フォーマット:
    - https://drive.google.com/file/d/FILE_ID/view
    - https://drive.google.com/open?id=FILE_ID
    - https://drive.google.com/uc?id=FILE_ID
    """
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
        r"/d/([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    raise ValueError(
        f"Google DriveのファイルIDを取得できませんでした。\n"
        f"URLを確認してください: {url}\n"
        f"正しい形式例: https://drive.google.com/file/d/xxxxxx/view"
    )


# -------------------------------------------------------
# Google Drive アクセストークン取得
# -------------------------------------------------------

def _get_drive_token(credentials_dict: dict) -> str:
    """サービスアカウント認証情報からGoogle Drive用アクセストークンを取得"""
    from google.oauth2.service_account import Credentials
    import google.auth.transport.requests

    creds = Credentials.from_service_account_info(
        credentials_dict,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


# -------------------------------------------------------
# DriveUploader クラス
# -------------------------------------------------------

class DriveUploader:
    """
    Google Drive から動画をダウンロードし TikTok にアップロードするクラス。
    同じURLは1セッション中キャッシュして重複アップロードを防ぐ。
    """

    def __init__(self, credentials_dict: dict):
        self.credentials_dict = credentials_dict
        self._video_id_cache: dict[str, str] = {}   # drive_url → tiktok video_id
        self._token: str | None = None

    def _access_token(self) -> str:
        """アクセストークンを取得（キャッシュ）"""
        if not self._token:
            self._token = _get_drive_token(self.credentials_dict)
        return self._token

    # -------------------------------------------------------
    # ダウンロード
    # -------------------------------------------------------

    def download_to_tempfile(self, drive_url: str) -> tuple[str, str]:
        """
        Google Drive からファイルをダウンロードして一時ファイルに保存する。

        Returns:
            (temp_file_path, original_file_name)
        """
        file_id = extract_drive_file_id(drive_url)
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}"}

        # ── メタデータ取得（ファイル名・サイズ確認） ──
        meta_resp = httpx.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers=headers,
            params={"fields": "name,mimeType,size"},
            timeout=30.0,
        )
        if meta_resp.status_code == 403:
            raise PermissionError(
                f"Google Driveファイルへのアクセス権がありません。\n"
                f"サービスアカウント (tiktok-ads-tool@winged-vigil-371710.iam.gserviceaccount.com) "
                f"とファイルを共有してください。\nファイルID: {file_id}"
            )
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        file_name = meta.get("name", f"video_{file_id}.mp4")
        file_size = int(meta.get("size", 0))
        logger.info(f"Driveダウンロード開始: {file_name} ({file_size / 1024 / 1024:.1f} MB)")

        # ── ダウンロード（ストリーミング） ──
        ext = Path(file_name).suffix or ".mp4"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp_path = tmp.name
        tmp.close()

        with httpx.stream(
            "GET",
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers=headers,
            params={"alt": "media"},
            follow_redirects=True,
            timeout=httpx.Timeout(connect=30.0, read=600.0, write=600.0, pool=30.0),
        ) as resp:
            if resp.status_code == 403:
                raise PermissionError(
                    f"ファイルのダウンロード権限がありません。ファイルID: {file_id}"
                )
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)

        actual_size = os.path.getsize(tmp_path)
        logger.success(f"✅ Driveダウンロード完了: {file_name} ({actual_size / 1024 / 1024:.1f} MB)")
        return tmp_path, file_name

    # -------------------------------------------------------
    # TikTok へアップロード
    # -------------------------------------------------------

    def upload_to_tiktok(
        self,
        drive_url: str,
        creative_manager,
        video_name: str | None = None,
    ) -> str:
        """
        Google Drive動画をダウンロードして TikTok にアップロードする。
        同じURLは2回目以降キャッシュを返す。

        Args:
            drive_url: Google DriveのファイルURL
            creative_manager: CreativeManager インスタンス
            video_name: TikTok上の動画名（省略時はファイル名）

        Returns:
            TikTokのvideo_id
        """
        # キャッシュヒット
        if drive_url in self._video_id_cache:
            cached = self._video_id_cache[drive_url]
            logger.info(f"動画IDキャッシュ使用: {cached} ({drive_url[:60]}...)")
            return cached

        tmp_path = None
        try:
            tmp_path, file_name = self.download_to_tempfile(drive_url)
            name = video_name or Path(file_name).stem

            result = creative_manager.upload_video(tmp_path, video_name=name)
            video_id = result.get("video_id", "")

            if video_id:
                self._video_id_cache[drive_url] = video_id
                logger.success(f"✅ TikTokアップロード完了: {name} → video_id={video_id}")
            else:
                raise RuntimeError("video_idが返ってきませんでした")

            return video_id

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
                logger.debug(f"一時ファイル削除: {tmp_path}")
