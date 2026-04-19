"""
TikTok Marketing API - ビジネスセンター・広告アカウント管理
複数BC・複数広告アカウントの一括管理
"""

from pathlib import Path
from typing import Optional

import yaml
from loguru import logger

from .client import TikTokClient
from .auth import TikTokAuth

CONFIG_PATH = Path(__file__).parent.parent / "config" / "accounts.yaml"


class BusinessManager:
    """ビジネスセンター・広告アカウント管理クラス"""

    def __init__(self, auth: TikTokAuth):
        self.auth = auth

    # -------------------------------------------------------
    # ビジネスセンター管理
    # -------------------------------------------------------

    def list_business_centers(self) -> list[dict]:
        """登録済みビジネスセンター一覧を返す"""
        bcs = self.auth.list_business_centers()
        logger.info(f"登録済みBC: {len(bcs)}件")
        return bcs

    def fetch_advertiser_info(self, bc_name: str) -> dict:
        """
        TikTok APIから広告主情報を取得
        """
        token = self.auth.get_valid_token(bc_name)
        client = TikTokClient(access_token=token)

        try:
            data = client.get("/oauth2/advertiser/get/", params={
                "app_id": self.auth.app_id,
                "secret": self.auth.app_secret,
            })
            return data
        finally:
            client.close()

    # -------------------------------------------------------
    # 広告アカウント管理
    # -------------------------------------------------------

    def fetch_ad_accounts(self, bc_name: str) -> list[dict]:
        """
        BC配下の広告アカウントをAPIから取得してYAMLに保存。
        自社作成アカウントも他BCから共有されたアカウントも全て取得する。
        """
        import json
        token = self.auth.get_valid_token(bc_name)
        bc_id = self._get_bc_id(bc_name)
        client = TikTokClient(access_token=token)

        try:
            # Step1: このOAuthトークンでアクセスできる全アカウントIDを取得
            logger.info(f"[{bc_name}] 全アカウントID取得中...")
            all_ids_data = client.get_all("/oauth2/advertiser/get/", params={
                "app_id": self.auth.app_id,
                "secret": self.auth.app_secret,
            })
            all_ids = [str(a.get("advertiser_id") or a.get("id", "")) for a in all_ids_data]
            all_ids = [i for i in all_ids if i]
            logger.info(f"[{bc_name}] 合計 {len(all_ids)} アカウントID取得")

            if not all_ids:
                logger.warning(f"[{bc_name}] 取得できるアカウントがありません")
                return []

            # Step2: 100件ずつ /advertiser/info/ で詳細取得
            logger.info(f"[{bc_name}] アカウント詳細取得中...")
            detailed = []
            for i in range(0, len(all_ids), 100):
                chunk = all_ids[i:i + 100]
                try:
                    info_data = client.get("/advertiser/info/", params={
                        "advertiser_ids": json.dumps(chunk),
                        "fields": json.dumps([
                            "advertiser_id", "name", "status",
                            "currency", "timezone", "owner_bc_id",
                        ]),
                    })
                    items = info_data.get("list", info_data) if isinstance(info_data, dict) else info_data
                    if isinstance(items, list):
                        detailed.extend(items)
                except Exception as e:
                    logger.warning(f"詳細取得失敗 (chunk {i // 100 + 1}): {e}")

            # Step3: owner_bc_id で所有元BCを分類してログ出力（絞り込みはしない）
            # 自社BCのアカウント: owner_bc_id == bc_id
            # 共有アカウント: owner_bc_id が別BCのもの → 除外せず全件含める
            owned = [a for a in detailed if str(a.get("owner_bc_id", "")) == str(bc_id)]
            shared = [a for a in detailed if str(a.get("owner_bc_id", "")) != str(bc_id)]
            logger.info(
                f"[{bc_name}] 自社BC所有: {len(owned)}件 / "
                f"他BCから共有: {len(shared)}件 / 合計: {len(detailed)}件"
            )
            if shared:
                shared_bc_ids = list(set(str(a.get("owner_bc_id", "")) for a in shared))
                logger.info(f"[{bc_name}] 共有元BC: {shared_bc_ids}")

            accounts = detailed  # 共有アカウントも含めて全件保存

            # YAMLに保存（手動追加分を上書きしないようにマージ）
            self._save_ad_accounts(bc_name, accounts)
            logger.success(f"✅ [{bc_name}] 広告アカウント {len(accounts)}件 取得・保存完了")
            return accounts
        finally:
            client.close()

    def add_ad_account_manually(
        self,
        bc_name: str,
        advertiser_id: str,
        account_name: str,
        currency: str = "JPY",
    ) -> bool:
        """
        APIで取得できない広告アカウントを手動でYAMLに追加する。
        既に同じ advertiser_id が存在する場合はスキップ。
        """
        config = self._load_config()
        for bc in config.get("business_centers", []):
            if bc.get("name") != bc_name:
                continue
            existing_ids = [str(a.get("advertiser_id", "")) for a in bc.get("ad_accounts", [])]
            if str(advertiser_id) in existing_ids:
                logger.warning(f"[{bc_name}] advertiser_id {advertiser_id} は既に登録済みです")
                return False
            bc.setdefault("ad_accounts", []).append({
                "advertiser_id": str(advertiser_id),
                "name": account_name,
                "status": "MANUAL",
                "currency": currency,
                "bc_id": "",
            })
            self._save_config(config)
            logger.success(f"✅ [{bc_name}] 手動追加: {account_name} ({advertiser_id})")
            return True
        raise ValueError(f"BC '{bc_name}' が見つかりません")

    def list_ad_accounts(self, bc_name: Optional[str] = None) -> list[dict]:
        """
        登録済み広告アカウント一覧を返す
        bc_name未指定時は全BC分を返す
        """
        config = self._load_config()
        result = []

        for bc in config.get("business_centers", []):
            if bc_name and bc.get("name") != bc_name:
                continue
            for account in bc.get("ad_accounts", []):
                result.append({
                    "bc_name": bc["name"],
                    "bc_id": bc.get("id", ""),
                    **account,
                })

        logger.info(f"広告アカウント: {len(result)}件")
        return result

    def get_client_for_account(self, advertiser_id: str, bc_name: str) -> TikTokClient:
        """
        特定の広告アカウント用のTikTokClientを返す
        """
        token = self.auth.get_valid_token(bc_name)
        return TikTokClient(access_token=token, advertiser_id=advertiser_id)

    def get_clients_for_all_accounts(self) -> list[dict]:
        """
        全広告アカウント分のクライアントをまとめて返す
        Returns: [{"bc_name": str, "advertiser_id": str, "client": TikTokClient}, ...]
        """
        accounts = self.list_ad_accounts()
        clients = []

        for account in accounts:
            try:
                client = self.get_client_for_account(
                    advertiser_id=account["advertiser_id"],
                    bc_name=account["bc_name"],
                )
                clients.append({
                    "bc_name": account["bc_name"],
                    "advertiser_id": account["advertiser_id"],
                    "account_name": account.get("name", ""),
                    "client": client,
                })
            except Exception as e:
                logger.error(f"[{account['bc_name']}] {account['advertiser_id']} クライアント作成失敗: {e}")

        logger.info(f"クライアント準備完了: {len(clients)}件")
        return clients

    # -------------------------------------------------------
    # ステータス確認
    # -------------------------------------------------------

    def check_all_tokens(self) -> list[dict]:
        """全BCのトークン状態をチェック"""
        from datetime import datetime
        config = self._load_config()
        results = []

        for bc in config.get("business_centers", []):
            name = bc.get("name", "")
            has_token = bool(bc.get("access_token"))
            expires_at = bc.get("token_expires_at", "")

            is_valid = False
            if has_token and expires_at:
                try:
                    exp = datetime.fromisoformat(expires_at)
                    is_valid = datetime.now() < exp
                except Exception:
                    pass

            status = "✅ 有効" if is_valid else ("⚠️ 期限切れ" if has_token else "❌ 未認証")
            logger.info(f"[{name}] {status} (expires: {expires_at})")

            results.append({
                "bc_name": name,
                "has_token": has_token,
                "is_valid": is_valid,
                "expires_at": expires_at,
                "status": status,
            })

        return results

    # -------------------------------------------------------
    # 内部ユーティリティ
    # -------------------------------------------------------

    def _load_config(self) -> dict:
        if not CONFIG_PATH.exists():
            return {"business_centers": []}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"business_centers": []}

    def _save_config(self, config: dict):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    def _get_bc_id(self, bc_name: str) -> str:
        config = self._load_config()
        for bc in config.get("business_centers", []):
            if bc.get("name") == bc_name:
                return bc.get("id", "")
        raise ValueError(f"BC '{bc_name}' が見つかりません")

    def _save_ad_accounts(self, bc_name: str, accounts: list[dict]):
        config = self._load_config()
        for bc in config.get("business_centers", []):
            if bc.get("name") == bc_name:
                bc["ad_accounts"] = [
                    {
                        "advertiser_id": str(a.get("advertiser_id") or a.get("id", "")),
                        "name": a.get("name", ""),
                        "status": a.get("status", ""),
                        "currency": a.get("currency", ""),
                        "bc_id": str(a.get("owner_bc_id", "")),
                    }
                    for a in accounts
                ]
                break
        self._save_config(config)
