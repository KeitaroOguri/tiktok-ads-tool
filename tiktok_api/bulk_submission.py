"""
一括入稿プロセッサー
Google SheetsのデータをTikTok APIへ一括入稿する
"""

from __future__ import annotations
from dataclasses import dataclass, field as dc_field
from loguru import logger
import pandas as pd

from .campaign import CampaignManager
from .adgroup import AdGroupManager
from .ad import AdManager
from .client import TikTokClient


# -------------------------------------------------------
# 日本語 → API値マッピング
# -------------------------------------------------------

OBJECTIVE_MAP = {
    "リーチ": "REACH",
    "トラフィック": "TRAFFIC",
    "動画視聴": "VIDEO_VIEWS",
    "コンバージョン": "CONVERSIONS",
    "アプリインストール": "APP_INSTALLS",
    "リード獲得": "LEAD_GENERATION",
    "フォロー": "FOLLOWERS",
    "カタログ販売": "CATALOG_SALES",
}

BUDGET_MODE_MAP = {
    "無制限": "BUDGET_MODE_INFINITE",
    "日予算": "BUDGET_MODE_DAILY",
    "総予算": "BUDGET_MODE_TOTAL",
}

PLACEMENT_TYPE_MAP = {
    "自動": "PLACEMENT_TYPE_AUTOMATIC",
    "手動": "PLACEMENT_TYPE_NORMAL",
}

SCHEDULE_TYPE_MAP = {
    "開始日から": "SCHEDULE_FROM_NOW",
    "期間指定": "SCHEDULE_START_END",
}

OPTIMIZATION_GOAL_MAP = {
    "クリック": "CLICK",
    "リーチ": "REACH",
    "コンバージョン": "CONVERT",
    "動画再生": "VIDEO_PLAY",
    "フォロー": "FOLLOW",
    "インプレッション": "SHOW",
}

BID_TYPE_MAP = {
    "自動入札": "BID_TYPE_NO_BID",
    "カスタム": "BID_TYPE_CUSTOM",
}

GENDER_MAP = {
    "すべて": "GENDER_UNLIMITED",
    "男性": "GENDER_MALE",
    "女性": "GENDER_FEMALE",
}

CTA_MAP = {
    "詳しくはこちら": "LEARN_MORE",
    "今すぐ購入": "SHOP_NOW",
    "アプリをダウンロード": "DOWNLOAD",
    "今すぐ申し込む": "APPLY_NOW",
    "今すぐ予約": "BOOK_NOW",
    "お問い合わせ": "CONTACT_US",
    "今すぐ登録": "SIGN_UP",
    "今すぐ視聴": "WATCH_NOW",
    "今すぐプレイ": "PLAY_GAME",
    "詳細を見る": "VIEW_MORE",
    "今すぐ注文": "ORDER_NOW",
    "今すぐ入手": "GET_NOW",
}


def _map(mapping: dict, raw: str, fallback: str = "") -> str:
    """マッピング変換。該当なければrawをそのまま使用（空なら fallback）"""
    if not raw:
        return fallback
    return mapping.get(raw, raw) or fallback


def _float_or_none(val) -> float | None:
    try:
        v = str(val).strip()
        return float(v) if v else None
    except (ValueError, TypeError):
        return None


def _list_from_csv(val) -> list[str]:
    return [x.strip() for x in str(val).split(",") if x.strip()] if val else []


# -------------------------------------------------------
# 結果データクラス
# -------------------------------------------------------

@dataclass
class SubmissionResult:
    row_index: int          # シート上のデータ行番号 (1始まり)
    entity_type: str        # campaign / adgroup / ad
    name: str
    status: str             # success / error / skipped
    created_id: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "row_index": self.row_index,
            "status": self.status,
            "created_id": self.created_id,
            "error": self.error,
        }


# -------------------------------------------------------
# プロセッサー本体
# -------------------------------------------------------

class BulkSubmissionProcessor:
    """Google Sheetsデータを読みTikTok APIへ一括入稿"""

    def __init__(self, client: TikTokClient):
        self.client = client
        self.cm = CampaignManager(client)
        self.agm = AdGroupManager(client)
        self.am = AdManager(client)

    # -------------------------------------------------------
    # キャンペーン
    # -------------------------------------------------------

    def process_campaigns(
        self, df: pd.DataFrame
    ) -> tuple[list[SubmissionResult], dict[str, str]]:
        """
        キャンペーンを作成
        Returns: (results, {キャンペーン名: campaign_id})
        """
        results: list[SubmissionResult] = []
        name_to_id: dict[str, str] = {}

        for i, row in df.iterrows():
            name = str(row.get("キャンペーン名", "")).strip()
            if not name:
                continue

            # 既にIDが入っていればスキップ
            existing_id = str(row.get("作成済みID", "")).strip()
            if existing_id:
                name_to_id[name] = existing_id
                results.append(SubmissionResult(
                    row_index=int(i) + 1,
                    entity_type="campaign",
                    name=name,
                    status="skipped",
                    created_id=existing_id,
                ))
                continue

            try:
                objective = _map(OBJECTIVE_MAP, str(row.get("目標タイプ", "")).strip())
                budget_mode = _map(BUDGET_MODE_MAP, str(row.get("予算タイプ", "")).strip(), "BUDGET_MODE_INFINITE")
                budget = _float_or_none(row.get("予算"))

                payload: dict = {
                    "campaign_name": name,
                    "objective_type": objective,
                    "budget_mode": budget_mode,
                }
                if budget and budget > 0:
                    payload["budget"] = budget

                campaign_id = self.cm.create(payload)
                name_to_id[name] = campaign_id
                results.append(SubmissionResult(
                    row_index=int(i) + 1,
                    entity_type="campaign",
                    name=name,
                    status="success",
                    created_id=campaign_id,
                ))

            except Exception as e:
                logger.error(f"キャンペーン作成失敗 [{name}]: {e}")
                results.append(SubmissionResult(
                    row_index=int(i) + 1,
                    entity_type="campaign",
                    name=name,
                    status="error",
                    error=str(e),
                ))

        success = sum(1 for r in results if r.status == "success")
        logger.info(f"キャンペーン処理完了: {success}/{len(results)}件成功")
        return results, name_to_id

    # -------------------------------------------------------
    # 広告グループ
    # -------------------------------------------------------

    def process_adgroups(
        self,
        df: pd.DataFrame,
        campaign_name_to_id: dict[str, str],
    ) -> tuple[list[SubmissionResult], dict[str, str]]:
        """
        広告グループを作成
        Returns: (results, {広告グループ名: adgroup_id})
        """
        results: list[SubmissionResult] = []
        name_to_id: dict[str, str] = {}

        for i, row in df.iterrows():
            ag_name = str(row.get("広告グループ名", "")).strip()
            camp_name = str(row.get("キャンペーン名", "")).strip()
            if not ag_name:
                continue

            existing_id = str(row.get("作成済みID", "")).strip()
            if existing_id:
                name_to_id[ag_name] = existing_id
                results.append(SubmissionResult(
                    row_index=int(i) + 1,
                    entity_type="adgroup",
                    name=ag_name,
                    status="skipped",
                    created_id=existing_id,
                ))
                continue

            # キャンペーンIDの解決
            campaign_id = campaign_name_to_id.get(camp_name, "")
            if not campaign_id:
                # campaign_nameがIDそのものかもしれない
                if camp_name.isdigit():
                    campaign_id = camp_name
                else:
                    results.append(SubmissionResult(
                        row_index=int(i) + 1,
                        entity_type="adgroup",
                        name=ag_name,
                        status="error",
                        error=f"キャンペーン '{camp_name}' のIDが見つかりません",
                    ))
                    continue

            try:
                placement_type = _map(PLACEMENT_TYPE_MAP, str(row.get("配置タイプ", "")).strip(), "PLACEMENT_TYPE_AUTOMATIC")
                budget_mode = _map(BUDGET_MODE_MAP, str(row.get("予算タイプ", "")).strip(), "BUDGET_MODE_INFINITE")
                schedule_type = _map(SCHEDULE_TYPE_MAP, str(row.get("スケジュール", "")).strip(), "SCHEDULE_FROM_NOW")
                optimization_goal = _map(OPTIMIZATION_GOAL_MAP, str(row.get("最適化目標", "")).strip())
                bid_type = _map(BID_TYPE_MAP, str(row.get("入札タイプ", "")).strip(), "BID_TYPE_NO_BID")
                gender_raw = str(row.get("性別", "")).strip()
                gender = _map(GENDER_MAP, gender_raw, "GENDER_UNLIMITED")

                payload: dict = {
                    "adgroup_name": ag_name,
                    "campaign_id": campaign_id,
                    "placement_type": placement_type,
                    "budget_mode": budget_mode,
                    "schedule_type": schedule_type,
                    "bid_type": bid_type,
                }

                if optimization_goal:
                    payload["optimization_goal"] = optimization_goal

                budget = _float_or_none(row.get("日予算"))
                if budget and budget > 0:
                    payload["budget"] = budget

                bid_price = _float_or_none(row.get("入札価格"))
                if bid_price and bid_price > 0:
                    payload["bid_price"] = bid_price

                start_time = str(row.get("開始日時", "")).strip()
                if start_time:
                    payload["start_time"] = start_time

                end_time = str(row.get("終了日時", "")).strip()
                if end_time:
                    payload["end_time"] = end_time

                location_ids = _list_from_csv(row.get("ターゲット地域"))
                if location_ids:
                    payload["location_ids"] = location_ids

                age_list = _list_from_csv(row.get("年齢層"))
                if age_list:
                    payload["age"] = age_list

                if gender:
                    payload["gender"] = gender

                adgroup_id = self.agm.create(payload)
                name_to_id[ag_name] = adgroup_id
                results.append(SubmissionResult(
                    row_index=int(i) + 1,
                    entity_type="adgroup",
                    name=ag_name,
                    status="success",
                    created_id=adgroup_id,
                ))

            except Exception as e:
                logger.error(f"広告グループ作成失敗 [{ag_name}]: {e}")
                results.append(SubmissionResult(
                    row_index=int(i) + 1,
                    entity_type="adgroup",
                    name=ag_name,
                    status="error",
                    error=str(e),
                ))

        success = sum(1 for r in results if r.status == "success")
        logger.info(f"広告グループ処理完了: {success}/{len(results)}件成功")
        return results, name_to_id

    # -------------------------------------------------------
    # 広告
    # -------------------------------------------------------

    def process_ads(
        self,
        df: pd.DataFrame,
        adgroup_name_to_id: dict[str, str],
    ) -> list[SubmissionResult]:
        """広告を作成"""
        results: list[SubmissionResult] = []

        for i, row in df.iterrows():
            ad_name = str(row.get("広告名", "")).strip()
            ag_name = str(row.get("広告グループ名", "")).strip()
            if not ad_name:
                continue

            existing_id = str(row.get("作成済みID", "")).strip()
            if existing_id:
                results.append(SubmissionResult(
                    row_index=int(i) + 1,
                    entity_type="ad",
                    name=ad_name,
                    status="skipped",
                    created_id=existing_id,
                ))
                continue

            adgroup_id = adgroup_name_to_id.get(ag_name, "")
            if not adgroup_id:
                if ag_name.isdigit():
                    adgroup_id = ag_name
                else:
                    results.append(SubmissionResult(
                        row_index=int(i) + 1,
                        entity_type="ad",
                        name=ad_name,
                        status="error",
                        error=f"広告グループ '{ag_name}' のIDが見つかりません",
                    ))
                    continue

            try:
                ad_format = str(row.get("広告フォーマット", "SINGLE_VIDEO")).strip() or "SINGLE_VIDEO"
                cta_raw = str(row.get("CTA", "")).strip()
                cta = _map(CTA_MAP, cta_raw)

                payload: dict = {
                    "adgroup_id": adgroup_id,
                    "ad_name": ad_name,
                    "ad_format": ad_format,
                }

                video_id = str(row.get("動画素材ID", "")).strip()
                if video_id:
                    payload["video_id"] = video_id

                image_id = str(row.get("サムネイル素材ID", "")).strip()
                if image_id:
                    payload["image_ids"] = [image_id]

                ad_text = str(row.get("広告テキスト", "")).strip()
                if ad_text:
                    payload["ad_text"] = ad_text

                if cta:
                    payload["call_to_action_type"] = cta

                landing_url = str(row.get("ランディングURL", "")).strip()
                if landing_url:
                    payload["landing_page_url"] = landing_url

                display_name = str(row.get("表示名", "")).strip()
                if display_name:
                    payload["display_name"] = display_name

                ad_id = self.am.create(payload)
                results.append(SubmissionResult(
                    row_index=int(i) + 1,
                    entity_type="ad",
                    name=ad_name,
                    status="success",
                    created_id=ad_id,
                ))

            except Exception as e:
                logger.error(f"広告作成失敗 [{ad_name}]: {e}")
                results.append(SubmissionResult(
                    row_index=int(i) + 1,
                    entity_type="ad",
                    name=ad_name,
                    status="error",
                    error=str(e),
                ))

        success = sum(1 for r in results if r.status == "success")
        logger.info(f"広告処理完了: {success}/{len(results)}件成功")
        return results
