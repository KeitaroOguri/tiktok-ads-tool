"""
TikTok Marketing API - クリエイティブ管理（動画・画像アップロード）
"""

from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from .client import TikTokClient

BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"

# 対応フォーマット
SUPPORTED_VIDEO_FORMATS = {".mp4", ".mov", ".mpeg", ".3gp", ".avi"}
SUPPORTED_IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".gif"}
MAX_VIDEO_SIZE_MB = 500
MAX_IMAGE_SIZE_MB = 10


class CreativeManager:
    """クリエイティブ（動画・画像）管理クラス"""

    def __init__(self, client: TikTokClient):
        self.client = client
        self.advertiser_id = client.advertiser_id
        self._access_token = client.access_token

    # -------------------------------------------------------
    # 動画アップロード
    # -------------------------------------------------------

    def upload_video(self, file_path: str, video_name: Optional[str] = None) -> dict:
        """
        動画ファイルをアップロード
        Returns: {"video_id": str, "video_name": str, ...}
        """
        path = Path(file_path)
        self._validate_file(path, SUPPORTED_VIDEO_FORMATS, MAX_VIDEO_SIZE_MB)

        name = video_name or path.stem
        logger.info(f"動画アップロード開始: {path.name} ({path.stat().st_size / 1024 / 1024:.1f}MB)")

        with open(path, "rb") as f:
            files = {"video_file": (path.name, f, "video/mp4")}
            data = {
                "advertiser_id": self.advertiser_id,
                "video_name": name,
            }
            resp = httpx.post(
                f"{BASE_URL}/file/video/ad/upload/",
                headers={"Access-Token": self._access_token},
                data=data,
                files=files,
                timeout=300.0,  # 大きいファイルは長めに
            )
            resp.raise_for_status()
            result = resp.json()

        if result.get("code") != 0:
            raise RuntimeError(f"動画アップロード失敗: {result.get('message')}")

        video_info = result["data"]
        logger.success(f"✅ 動画アップロード完了: {name} (ID: {video_info.get('video_id')})")
        return video_info

    def upload_video_by_url(self, url: str, video_name: str) -> dict:
        """
        URLから動画をアップロード
        Returns: {"video_id": str, ...}
        """
        body = {
            "advertiser_id": self.advertiser_id,
            "video_url": url,
            "video_name": video_name,
        }
        data = self.client.post("/file/video/ad/upload/", body=body)
        logger.success(f"✅ 動画URLアップロード完了: {video_name} (ID: {data.get('video_id')})")
        return data

    def upload_videos_bulk(self, file_paths: list[str]) -> list[dict]:
        """
        複数動画を一括アップロード
        Returns: [{"video_id": str, "file_path": str, "success": bool}, ...]
        """
        results = []
        for i, file_path in enumerate(file_paths):
            logger.info(f"動画アップロード ({i+1}/{len(file_paths)}): {file_path}")
            try:
                info = self.upload_video(file_path)
                results.append({"file_path": file_path, "success": True, **info})
            except Exception as e:
                logger.error(f"❌ アップロード失敗: {file_path} → {e}")
                results.append({"file_path": file_path, "success": False, "error": str(e)})

        success_count = sum(1 for r in results if r["success"])
        logger.info(f"一括アップロード完了: 成功 {success_count}/{len(file_paths)}件")
        return results

    # -------------------------------------------------------
    # 画像アップロード
    # -------------------------------------------------------

    def upload_image(self, file_path: str, image_name: Optional[str] = None) -> dict:
        """
        画像ファイルをアップロード
        Returns: {"image_id": str, "image_url": str, ...}
        """
        path = Path(file_path)
        self._validate_file(path, SUPPORTED_IMAGE_FORMATS, MAX_IMAGE_SIZE_MB)

        name = image_name or path.stem
        logger.info(f"画像アップロード開始: {path.name}")

        with open(path, "rb") as f:
            files = {"image_file": (path.name, f, "image/jpeg")}
            data = {
                "advertiser_id": self.advertiser_id,
                "image_name": name,
            }
            resp = httpx.post(
                f"{BASE_URL}/file/image/ad/upload/",
                headers={"Access-Token": self._access_token},
                data=data,
                files=files,
                timeout=60.0,
            )
            resp.raise_for_status()
            result = resp.json()

        if result.get("code") != 0:
            raise RuntimeError(f"画像アップロード失敗: {result.get('message')}")

        image_info = result["data"]
        logger.success(f"✅ 画像アップロード完了: {name} (ID: {image_info.get('image_id')})")
        return image_info

    # -------------------------------------------------------
    # クリエイティブ情報取得
    # -------------------------------------------------------

    def get_video_info(self, video_ids: list[str]) -> list[dict]:
        """動画情報を取得"""
        data = self.client.get("/file/video/ad/search/", params={
            "advertiser_id": self.advertiser_id,
            "filtering": {"video_ids": video_ids},
        })
        return data.get("list", [])

    def get_image_info(self, image_ids: list[str]) -> list[dict]:
        """画像情報を取得"""
        data = self.client.get("/file/image/ad/get/", params={
            "advertiser_id": self.advertiser_id,
            "image_ids": image_ids,
        })
        return data.get("list", [])

    # -------------------------------------------------------
    # バリデーション
    # -------------------------------------------------------

    def _validate_file(self, path: Path, supported_formats: set, max_size_mb: int):
        """ファイルの存在・拡張子・サイズを検証"""
        if not path.exists():
            raise FileNotFoundError(f"ファイルが見つかりません: {path}")

        if path.suffix.lower() not in supported_formats:
            raise ValueError(f"非対応フォーマット: {path.suffix}（対応: {supported_formats}）")

        size_mb = path.stat().st_size / 1024 / 1024
        if size_mb > max_size_mb:
            raise ValueError(f"ファイルサイズ超過: {size_mb:.1f}MB（上限: {max_size_mb}MB）")
