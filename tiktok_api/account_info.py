"""
広告アカウントに連携済みのピクセル・アイデンティティ情報を取得するモジュール
"""

from __future__ import annotations
from loguru import logger
from .client import TikTokClient


class PixelManager:
    """TikTok ピクセル一覧取得"""

    def __init__(self, client: TikTokClient):
        self.client = client
        self.advertiser_id = client.advertiser_id
        self._last_raw = None   # デバッグ用: 最後のAPIレスポンス

    def list_pixels(self) -> list[dict]:
        """
        連携済みピクセル一覧を返す
        Returns: [{"pixel_id": str, "name": str}, ...]
        """
        # TikTok Marketing API v1.3 のピクセル一覧エンドポイントを複数試す
        endpoints = [
            ("/pixel/list/",        {"advertiser_id": self.advertiser_id, "page_size": 100}),
            ("/pixel/list/",        {"advertiser_id": self.advertiser_id}),
        ]

        for path, params in endpoints:
            try:
                data = self.client.get(path, params=params)
                self._last_raw = data
                logger.debug(f"ピクセルAPI raw response ({path}): {data}")

                # レスポンス構造を柔軟に対応
                pixels = (
                    data.get("list") or
                    data.get("pixels") or
                    data.get("data", {}).get("list") if isinstance(data.get("data"), dict) else None or
                    []
                )
                if not isinstance(pixels, list):
                    pixels = []

                logger.info(f"ピクセル取得: {len(pixels)}件 ({path})")
                return [
                    {
                        "pixel_id": p.get("pixel_id", ""),
                        "name": p.get("name") or p.get("pixel_name") or p.get("pixel_id", ""),
                    }
                    for p in pixels
                    if p.get("pixel_id")
                ]
            except Exception as e:
                logger.warning(f"ピクセル取得失敗 ({path}): {e}")
                self._last_raw = str(e)

        return []

    def dropdown_options(self) -> list[str]:
        """
        スプレッドシート用プルダウン選択肢を生成
        形式: "ピクセル名 [pixel_id]"
        """
        pixels = self.list_pixels()
        return [f"{p['name']} [{p['pixel_id']}]" for p in pixels]


class IdentityManager:
    """TikTok アイデンティティ（連携アカウント）一覧取得"""

    def __init__(self, client: TikTokClient):
        self.client = client
        self.advertiser_id = client.advertiser_id
        self._last_raw = None   # デバッグ用

    def list_identities(self) -> list[dict]:
        """
        連携済みアイデンティティ一覧を返す
        Returns: [{"identity_id": str, "identity_type": str, "display_name": str}, ...]
        """
        # identity_type ごとに取得 + まとめて取得を試す
        all_results = []
        identity_types = ["BC_AUTH_TT", "CUSTOMIZED_USER", "AUTH_CODE"]

        for id_type in identity_types:
            try:
                data = self.client.get(
                    "/identity/list/",
                    params={
                        "advertiser_id": self.advertiser_id,
                        "identity_type": id_type,
                        "page_size": 100,
                    },
                )
                self._last_raw = data
                logger.debug(f"アイデンティティAPI raw ({id_type}): {data}")

                items = (
                    data.get("list") or
                    data.get("identity_list") or
                    []
                )
                if not isinstance(items, list):
                    items = []

                logger.info(f"アイデンティティ取得 ({id_type}): {len(items)}件")

                for item in items:
                    identity_id = (
                        item.get("identity_id") or
                        item.get("tiktok_item_id") or
                        item.get("id") or
                        ""
                    )
                    display_name = (
                        item.get("display_name") or
                        item.get("identity_name") or
                        item.get("name") or
                        item.get("account_name") or
                        identity_id
                    )
                    if identity_id:
                        all_results.append({
                            "identity_id": identity_id,
                            "identity_type": id_type,
                            "display_name": display_name,
                        })

            except Exception as e:
                logger.warning(f"アイデンティティ取得失敗 ({id_type}): {e}")
                self._last_raw = str(e)

        return all_results

    def dropdown_options(self) -> list[str]:
        """
        スプレッドシート用プルダウン選択肢を生成
        形式: "表示名 [identity_id|identity_type]"
        """
        identities = self.list_identities()
        return [
            f"{i['display_name']} [{i['identity_id']}|{i['identity_type']}]"
            for i in identities
        ]

    @staticmethod
    def parse_option(value: str) -> tuple[str, str]:
        """
        "表示名 [identity_id|identity_type]" → (identity_id, identity_type)
        """
        import re
        m = re.search(r"\[([^\|\]]+)\|([^\]]+)\]", value)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return value.strip(), "BC_AUTH_TT"
