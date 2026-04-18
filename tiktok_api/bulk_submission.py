"""
一括入稿プロセッサー（TikTokエクスポート形式準拠シート対応）

列名はTikTok広告管理画面のエクスポートExcelと同じ日本語名を使用。
API送信時にTikTok Export値 → TikTok API値 のマッピングを行う。
"""

from __future__ import annotations
from dataclasses import dataclass
from loguru import logger
import pandas as pd

from .campaign import CampaignManager
from .adgroup import AdGroupManager
from .ad import AdManager
from .creative import CreativeManager
from .client import TikTokClient


# -------------------------------------------------------
# TikTok Export値 → TikTok API値 マッピング
# -------------------------------------------------------

# 目的（Objective）
OBJECTIVE_MAP = {
    "Sales":            "CONVERSIONS",
    "Traffic":          "TRAFFIC",
    "Reach":            "REACH",
    "Video Views":      "VIDEO_VIEWS",
    "App Installs":     "APP_INSTALLS",
    "Lead Generation":  "LEAD_GENERATION",
    "Followers":        "FOLLOWERS",
}

# キャンペーン予算タイプ
CAMPAIGN_BUDGET_MODE_MAP = {
    "Daily":    "BUDGET_MODE_DAY",
    "Lifetime": "BUDGET_MODE_TOTAL",
    "No Limit": "BUDGET_MODE_INFINITE",
}

# 広告グループ予算タイプ
ADGROUP_BUDGET_MODE_MAP = {
    "Daily":    "BUDGET_MODE_DAY",
    "Lifetime": "BUDGET_MODE_TOTAL",
    "No Limit": "BUDGET_MODE_INFINITE",
    "":         "BUDGET_MODE_INFINITE",
}

# プレースメントタイプ
PLACEMENT_TYPE_MAP = {
    "Automatic": "PLACEMENT_TYPE_AUTOMATIC",
    "Select":    "PLACEMENT_TYPE_NORMAL",
}

# 最適化目標
OPTIMIZATION_GOAL_MAP = {
    "Conversion":  "CONVERT",
    "Click":       "CLICK",
    "Reach":       "REACH",
    "Video Play":  "VIDEO_PLAY",
    "Follow":      "FOLLOW",
    "Impression":  "SHOW",
}

# 課金イベント
BILLING_EVENT_MAP = {
    "oCPM": "OCPM",
    "CPM":  "CPM",
    "CPC":  "CPC",
    "CPV":  "CPV",
}

# 入札タイプ
BID_TYPE_MAP = {
    "Lowest Cost": "BID_TYPE_NO_BID",
    "Cost Cap":    "BID_TYPE_CUSTOM",
    "Bid Cap":     "BID_TYPE_CUSTOM",
}

# 性別
GENDER_MAP = {
    "All":    "GENDER_UNLIMITED",
    "Male":   "GENDER_MALE",
    "Female": "GENDER_FEMALE",
}

# CTAタイプ
CTA_MAP = {
    "Learn More":   "LEARN_MORE",
    "Shop Now":     "SHOP_NOW",
    "Download":     "DOWNLOAD",
    "Apply Now":    "APPLY_NOW",
    "Book Now":     "BOOK_NOW",
    "Contact Us":   "CONTACT_US",
    "Sign Up":      "SIGN_UP",
    "Watch Now":    "WATCH_NOW",
    "Play Game":    "PLAY_GAME",
    "View More":    "VIEW_MORE",
    "Order Now":    "ORDER_NOW",
    "Get Now":      "GET_NOW",
    "Dynamic":      "",           # Dynamic → CTA指定なし（TikTokが自動選択）
}

# 広告フォーマット
AD_FORMAT_MAP = {
    "Single video": "SINGLE_VIDEO",
    "Image":        "IMAGE",
    "Spark Ads":    "SPARK_ADS",
}

# アイデンティティタイプ
IDENTITY_TYPE_MAP = {
    "TTBC Authorized Post": "BC_AUTH_TT",
    "CUSTOM_USER":          "CUSTOMIZED_USER",
    "AUTH_CODE":            "AUTH_CODE",
}

# 年齢帯（エクスポート形式 → API値）
AGE_MAP = {
    "13-17": "AGE_13_17",
    "18-24": "AGE_18_24",
    "25-34": "AGE_25_34",
    "35-44": "AGE_35_44",
    "45-54": "AGE_45_54",
    "55+":   "AGE_55_100",
    "55-100":"AGE_55_100",
    "AGE_13_17": "AGE_13_17",
    "AGE_18_24": "AGE_18_24",
    "AGE_25_34": "AGE_25_34",
    "AGE_35_44": "AGE_35_44",
    "AGE_45_54": "AGE_45_54",
    "AGE_55_100":"AGE_55_100",
}


# -------------------------------------------------------
# ユーティリティ
# -------------------------------------------------------

def _s(row: pd.Series, key: str) -> str:
    """行から文字列を取得（strip済み、nan→空文字）"""
    v = row.get(key, "")
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s in ("nan", "None") else s


def _f(row: pd.Series, key: str) -> float | None:
    """行から数値を取得。空/変換失敗はNone"""
    try:
        v = str(row.get(key, "")).strip()
        if not v or v in ("nan", "None"):
            return None
        return float(v) if v else None
    except (ValueError, TypeError):
        return None


def _csv(row: pd.Series, key: str) -> list[str]:
    """カンマ区切り文字列をリストに変換"""
    raw = _s(row, key)
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else []


def _map(mapping: dict, raw: str, default: str = "") -> str:
    """マッピング変換。マップにない値はそのまま返す（default指定時はdefault）"""
    if not raw:
        return default
    return mapping.get(raw, raw) if raw not in mapping else mapping[raw]


def _strip_id(val: str) -> str:
    """'id:1234567890' や 'id:uuid-...' → プレフィックス除去"""
    s = val.strip()
    if s.lower().startswith("id:"):
        return s[3:].strip()
    return s


def _parse_locations(raw: str) -> list[str]:
    """
    'L1865694,L1864226,...' → ['1865694', '1864226', ...]
    '1865694,1864226,...'  → ['1865694', '1864226', ...]
    """
    if not raw:
        return []
    ids = []
    for part in raw.split(","):
        p = part.strip().lstrip("L")
        if p and p not in ("nan", "None"):
            ids.append(p)
    return ids


def _parse_ages(raw: str) -> list[str]:
    """
    '18-24,25-34,55+' → ['AGE_18_24', 'AGE_25_34', 'AGE_55_100']
    'All' / '' → []
    """
    if not raw or raw.strip() in ("", "All", "nan"):
        return []
    result = []
    for part in raw.split(","):
        p = part.strip()
        api_val = AGE_MAP.get(p, "")
        if api_val:
            result.append(api_val)
        elif p.startswith("AGE_"):
            result.append(p)
    return result


# -------------------------------------------------------
# 結果データクラス
# -------------------------------------------------------

@dataclass
class UnifiedResult:
    row_index: int          # 1始まりのデータ行番号
    status: str = ""        # success / error / skipped
    campaign_id: str = ""
    adgroup_id: str = ""
    ad_id: str = ""
    video_id: str = ""      # Drive経由でアップロードした場合に格納
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "row_index": self.row_index,
            "status": self.status,
            "campaign_id": self.campaign_id,
            "adgroup_id": self.adgroup_id,
            "ad_id": self.ad_id,
            "video_id": self.video_id,
            "error": self.error,
        }


# -------------------------------------------------------
# ペイロードビルダー
# -------------------------------------------------------

def _build_campaign_payload(row: pd.Series) -> dict:
    name        = _s(row, "キャンペーン名")
    objective   = _map(OBJECTIVE_MAP,              _s(row, "目的"),               "CONVERSIONS")
    budget_mode = _map(CAMPAIGN_BUDGET_MODE_MAP,   _s(row, "キャンペーン予算タイプ"), "BUDGET_MODE_INFINITE")
    budget      = _f(row, "キャンペーン予算")

    payload: dict = {
        "campaign_name": name,
        "objective_type": objective,
        "budget_mode": budget_mode,
    }
    if budget and budget > 0:
        payload["budget"] = budget
    return payload


def _build_adgroup_payload(row: pd.Series, campaign_id: str) -> dict:
    from datetime import datetime, timezone

    name         = _s(row, "広告セット名")
    placement    = _map(PLACEMENT_TYPE_MAP,    _s(row, "プレースメントタイプ"),     "PLACEMENT_TYPE_AUTOMATIC")
    budget_mode  = _map(ADGROUP_BUDGET_MODE_MAP, _s(row, "広告セット予算タイプ"), "BUDGET_MODE_INFINITE")
    opt_goal     = _map(OPTIMIZATION_GOAL_MAP, _s(row, "最適化の目標"),             "CONVERT")
    billing_raw  = _s(row, "課金イベント") or "oCPM"
    billing      = BILLING_EVENT_MAP.get(billing_raw, "OCPM")
    bid_type     = _map(BID_TYPE_MAP,          _s(row, "入札タイプ"),               "BID_TYPE_NO_BID")
    gender       = _map(GENDER_MAP,            _s(row, "性別"),                     "GENDER_UNLIMITED")

    # スケジュール: 開始時刻は必須
    start = _s(row, "開始時刻")
    if not start:
        start = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 形式を正規化: '2026/4/18 17:58' → '2026-04-18 17:58:00'
        import re
        if re.match(r"\d{4}/\d{1,2}/\d{1,2}", start):
            from datetime import datetime as dt
            for fmt in ["%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"]:
                try:
                    start = dt.strptime(start, fmt).strftime("%Y-%m-%d %H:%M:%S")
                    break
                except ValueError:
                    continue

    end_raw = _s(row, "終了時刻")
    end = ""
    if end_raw and end_raw not in ("No Limit", "NoLimit"):
        import re
        if re.match(r"\d{4}/\d{1,2}/\d{1,2}", end_raw):
            from datetime import datetime as dt
            for fmt in ["%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"]:
                try:
                    end = dt.strptime(end_raw, fmt).strftime("%Y-%m-%d %H:%M:%S")
                    break
                except ValueError:
                    continue
        elif re.match(r"\d{4}-\d{2}-\d{2}", end_raw):
            end = end_raw

    schedule = "SCHEDULE_START_END" if end else "SCHEDULE_FROM_NOW"

    payload: dict = {
        "adgroup_name": name,
        "campaign_id": campaign_id,
        "placement_type": placement,
        "budget_mode": budget_mode,
        "schedule_type": schedule,
        "schedule_start_time": start,
        "billing_event": billing,
        "bid_type": bid_type,
    }

    if opt_goal:
        payload["optimization_goal"] = opt_goal

    if end:
        payload["schedule_end_time"] = end

    # 予算
    budget = _f(row, "広告セット予算")
    if budget and budget > 0:
        payload["budget"] = budget

    # 入札価格（Cost Cap / Bid Cap のみ）
    bid_price = _f(row, "入札")
    if bid_price and bid_price > 0:
        payload["bid_price"] = bid_price

    # ロケーション（デフォルト: 日本=7709）
    locations = _parse_locations(_s(row, "ロケーション"))
    payload["location_ids"] = locations if locations else ["7709"]

    # 性別
    if gender:
        payload["gender"] = gender

    # 年齢
    ages = _parse_ages(_s(row, "年齢"))
    if ages:
        payload["age"] = ages

    # 言語
    lang = _s(row, "言語")
    if lang and lang not in ("All", ""):
        payload["languages"] = [lang]

    # ピクセル
    pixel_id = _s(row, "TikTok ピクセル ID")
    pixel_event = _s(row, "ピクセルイベント")
    if pixel_id:
        payload["pixel_id"] = pixel_id
    if pixel_event:
        # 数値の場合はintに変換
        try:
            payload["pixel_event_type"] = int(float(pixel_event))
        except (ValueError, TypeError):
            payload["pixel_event_type"] = pixel_event

    # オーディエンス
    audience_ids = _csv(row, "ユーザーリスト設定ID")
    if audience_ids:
        payload["audience_ids"] = audience_ids

    excluded_ids = _csv(row, "ユーザーリスト除外ID")
    if excluded_ids:
        payload["excluded_audience_ids"] = excluded_ids

    # フリークエンシー上限
    freq = _f(row, "フリークエンシー上限")
    if freq and freq > 0:
        payload["frequency"] = int(freq)

    return payload


def _build_ad_payload(
    row: pd.Series,
    adgroup_id: str,
    override_video_id: str = "",
) -> dict:
    name       = _s(row, "広告名")
    ad_format_raw = _s(row, "広告フォーマット") or "Single video"
    ad_format  = AD_FORMAT_MAP.get(ad_format_raw, "SINGLE_VIDEO")

    # 動画ID: override（Drive経由アップロード済み）> シートの「動画名」列
    # ※ 「動画名」列にはvideo_idまたは動画ファイル名が入る。
    #   Drive経由のupload後はvideo_idをここに書き戻す。
    video_id   = override_video_id or _s(row, "動画名")

    ad_text    = _s(row, "テキスト")
    cta_raw    = _s(row, "CTAタイプ")
    cta        = CTA_MAP.get(cta_raw, cta_raw) if cta_raw else ""
    url        = _s(row, "Web URL")

    # アイデンティティ
    identity_type_raw = _s(row, "アイデンティティタイプ")
    identity_type     = IDENTITY_TYPE_MAP.get(identity_type_raw, identity_type_raw)
    identity_id_raw   = _s(row, "アイデンティティID")
    identity_id       = _strip_id(identity_id_raw) if identity_id_raw else ""

    # トラッキングURL
    imp_url   = _s(row, "インプレッショントラッキング URL")
    click_url = _s(row, "クリックトラッキングURL")

    payload: dict = {
        "adgroup_id": adgroup_id,
        "ad_name": name,
        "ad_format": ad_format,
    }

    if video_id:
        payload["video_id"] = video_id
    if ad_text:
        payload["ad_text"] = ad_text
    if cta:
        payload["call_to_action_type"] = cta
    if url:
        payload["landing_page_url"] = url
    if identity_type and identity_id:
        payload["identity_type"] = identity_type
        payload["identity_id"] = identity_id
    if imp_url:
        payload["impression_tracking_url"] = imp_url
    if click_url:
        payload["click_tracking_url"] = click_url

    return payload


# -------------------------------------------------------
# プロセッサー本体
# -------------------------------------------------------

class BulkSubmissionProcessor:
    """統合シートのデータを TikTok API へ一括入稿"""

    def __init__(self, client: TikTokClient, gcp_credentials: dict | None = None):
        self.client = client
        self.cm       = CampaignManager(client)
        self.agm      = AdGroupManager(client)
        self.am       = AdManager(client)
        self.creative = CreativeManager(client)
        self.gcp_credentials = gcp_credentials
        self._drive_uploader = None

    def _get_drive_uploader(self):
        """DriveUploaderを遅延初期化して返す"""
        if self._drive_uploader is None:
            if not self.gcp_credentials:
                raise RuntimeError(
                    "Google Drive動画URLを使用するにはGCPサービスアカウント認証情報が必要です"
                )
            from .drive_uploader import DriveUploader
            self._drive_uploader = DriveUploader(self.gcp_credentials)
        return self._drive_uploader

    def process_unified(self, df: pd.DataFrame) -> list[UnifiedResult]:
        """
        統合シートの全行を処理する。

        - キャンペーン: 同じ「キャンペーン名」は初回のみ作成（キャッシュ）
        - 広告グループ: 同じ「(キャンペーン名, 広告セット名)」は初回のみ作成
        - 広告: 全行で1件ずつ作成
        - 「キャンペーンID」「広告セット ID」「広告ID」に既存IDがあればスキップ

        Returns: [UnifiedResult] （行ごと）
        """
        results: list[UnifiedResult] = []

        # キャッシュ
        campaign_cache: dict[str, str] = {}         # camp_name → campaign_id
        adgroup_cache: dict[tuple, str] = {}         # (camp_name, ag_name) → adgroup_id

        for i, row in df.iterrows():
            row_result = UnifiedResult(row_index=int(i) + 1)

            camp_name = _s(row, "キャンペーン名")
            ag_name   = _s(row, "広告セット名")
            ad_name   = _s(row, "広告名")

            # 完全空行はスキップ
            if not camp_name and not ag_name and not ad_name:
                continue

            # ── キャンペーン ────────────────────────
            if camp_name:
                existing_camp_id = _strip_id(_s(row, "キャンペーンID")) if _s(row, "キャンペーンID") else ""
                if existing_camp_id:
                    campaign_cache[camp_name] = existing_camp_id
                    row_result.campaign_id = existing_camp_id
                elif camp_name in campaign_cache:
                    row_result.campaign_id = campaign_cache[camp_name]
                else:
                    try:
                        payload = _build_campaign_payload(row)
                        camp_id = self.cm.create(payload)
                        campaign_cache[camp_name] = camp_id
                        row_result.campaign_id = camp_id
                    except Exception as e:
                        row_result.status = "error"
                        row_result.error = f"キャンペーン作成失敗: {e}"
                        results.append(row_result)
                        continue

            # ── 広告グループ ─────────────────────────
            if ag_name:
                ag_key = (camp_name, ag_name)
                existing_ag_id = _strip_id(_s(row, "広告セット ID")) if _s(row, "広告セット ID") else ""
                if existing_ag_id:
                    adgroup_cache[ag_key] = existing_ag_id
                    row_result.adgroup_id = existing_ag_id
                elif ag_key in adgroup_cache:
                    row_result.adgroup_id = adgroup_cache[ag_key]
                else:
                    try:
                        if not row_result.campaign_id:
                            raise ValueError("キャンペーンIDが取得できていません")
                        payload = _build_adgroup_payload(row, row_result.campaign_id)
                        ag_id = self.agm.create(payload)
                        adgroup_cache[ag_key] = ag_id
                        row_result.adgroup_id = ag_id
                    except Exception as e:
                        row_result.status = "error"
                        row_result.error = f"広告グループ作成失敗: {e}"
                        results.append(row_result)
                        continue

            # ── 広告 ─────────────────────────────────
            if ad_name:
                existing_ad_id = _strip_id(_s(row, "広告ID")) if _s(row, "広告ID") else ""
                if existing_ad_id:
                    row_result.ad_id = existing_ad_id
                    row_result.status = "skipped"
                else:
                    try:
                        if not row_result.adgroup_id:
                            raise ValueError("広告グループIDが取得できていません")

                        # Google Drive動画URLがあれば先にTikTokへアップロード
                        drive_url = _s(row, "Google Drive動画URL")
                        video_id  = _s(row, "動画名")  # 既存video_idまたは動画名
                        if drive_url and not video_id:
                            logger.info(f"Google Drive動画をアップロード中: {drive_url[:60]}...")
                            uploader = self._get_drive_uploader()
                            video_id = uploader.upload_to_tiktok(
                                drive_url=drive_url,
                                creative_manager=self.creative,
                                video_name=ad_name,
                            )
                            row_result.video_id = video_id
                            logger.success(f"✅ Drive→TikTok アップロード完了: video_id={video_id}")

                        payload = _build_ad_payload(row, row_result.adgroup_id, override_video_id=video_id)
                        ad_id = self.am.create(payload)
                        row_result.ad_id = ad_id
                        row_result.status = "success"
                    except Exception as e:
                        row_result.status = "error"
                        row_result.error = f"広告作成失敗: {e}"

            results.append(row_result)

        success  = sum(1 for r in results if r.status == "success")
        skipped  = sum(1 for r in results if r.status == "skipped")
        errors   = sum(1 for r in results if r.status == "error")
        logger.info(
            f"一括入稿完了: 成功{success} / スキップ{skipped} / エラー{errors} / 合計{len(results)}件"
        )
        return results
