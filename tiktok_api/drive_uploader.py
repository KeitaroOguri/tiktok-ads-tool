"""
Google Drive動画 → TikTokクリエイティブライブラリ アップローダー

【フロー】
1. スプレッドシートの「動画素材ID」が入力済み → そのまま使用（アップロードなし）
2. 「動画素材ID」が空 + 「Google Drive動画URL」がある → ダウンロード→アップロード→video_id取得
3. 取得したvideo_idをスプレッドシートの「動画素材ID」列に書き戻す
   → 次回以降は「動画素材ID」が埋まっているので再アップロードなし

【準備】
Google DriveのファイルをサービスアカウントのEmailと共有する（閲覧者権限でOK）
  tiktok-ads-tool@winged-vigil-371710.iam.gserviceaccount.com
"""

from __future__ import annotations
import os
import re
import tempfile
from pathlib import Path
from loguru import logger
import httpx


# -------------------------------------------------------
# Drive URL からファイルIDを抽出
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
        f"URL: {url}\n"
        f"正しい形式例: https://drive.google.com/file/d/xxxxxx/view"
    )


# -------------------------------------------------------
# アクセストークン取得
# -------------------------------------------------------

def _get_drive_token(credentials_dict: dict) -> str:
    from google.oauth2.service_account import Credentials
    import google.auth.transport.requests

    creds = Credentials.from_service_account_info(
        credentials_dict,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


# -------------------------------------------------------
# DriveUploader
# -------------------------------------------------------

class DriveUploader:
    """
    Google Drive から動画をダウンロードし TikTok にアップロードするクラス。
    セッション内では同一URLのアップロードをメモリキャッシュで防ぐ。
    """

    def __init__(self, credentials_dict: dict):
        self.credentials_dict = credentials_dict
        self._token: str | None = None
        self._cache: dict[str, str] = {}   # file_id → video_id（セッション内キャッシュ）

    def _access_token(self) -> str:
        if not self._token:
            self._token = _get_drive_token(self.credentials_dict)
        return self._token

    def download_to_tempfile(self, drive_url: str) -> tuple[str, str]:
        """
        Google Drive からダウンロードして一時ファイルに保存する。
        Returns: (temp_file_path, original_file_name)
        """
        file_id = extract_drive_file_id(drive_url)
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}"}

        # メタデータ取得
        meta_resp = httpx.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers=headers,
            params={"fields": "name,mimeType,size"},
            timeout=30.0,
        )
        if meta_resp.status_code == 403:
            raise PermissionError(
                f"アクセス権がありません。サービスアカウントとファイルを共有してください。\n"
                f"tiktok-ads-tool@winged-vigil-371710.iam.gserviceaccount.com\n"
                f"ファイルID: {file_id}"
            )
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        file_name = meta.get("name", f"video_{file_id}.mp4")
        file_size = int(meta.get("size", 0))
        logger.info(f"Driveダウンロード開始: {file_name} ({file_size / 1024 / 1024:.1f} MB)")

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
                raise PermissionError(f"ダウンロード権限がありません。ファイルID: {file_id}")
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)

        logger.success(
            f"✅ Driveダウンロード完了: {file_name} "
            f"({os.path.getsize(tmp_path) / 1024 / 1024:.1f} MB)"
        )
        return tmp_path, file_name

    def upload_to_tiktok(
        self,
        drive_url: str,
        creative_manager,
        video_name: str | None = None,
    ) -> str:
        """
        Google Drive動画をTikTokにアップロードする。
        セッション内で同じURLが来た場合はキャッシュを返す。

        Returns: video_id
        """
        file_id = extract_drive_file_id(drive_url)

        # セッション内キャッシュ
        if file_id in self._cache:
            vid = self._cache[file_id]
            logger.info(f"セッションキャッシュヒット: video_id={vid}")
            return vid

        tmp_path = None
        try:
            tmp_path, file_name = self.download_to_tempfile(drive_url)
            name = video_name or Path(file_name).stem

            result = creative_manager.upload_video(tmp_path, video_name=name)
            video_id = result.get("video_id", "")
            if not video_id:
                raise RuntimeError("video_idが返ってきませんでした")

            self._cache[file_id] = video_id
            logger.success(f"✅ Drive→TikTok完了: {name} → video_id={video_id}")
            return video_id

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
