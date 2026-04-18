"""
TikTok広告エクスポートExcel → 統合シート変換モジュール（直接コピー方式）

シートの列名がTikTokエクスポートExcelと同じ日本語名を使用しているため、
変換はほぼ直接コピーで完了する。
"""

from __future__ import annotations
import re
from pathlib import Path
import pandas as pd
from loguru import logger


def _strip_id_prefix(val) -> str:
    """'id:1234567890' → '1234567890'（エクスポートIDのプレフィックス除去）"""
    s = str(val).strip()
    if s.lower().startswith("id:"):
        return s[3:].strip()
    return "" if s in ("nan", "None", "") else s


def _safe_str(val) -> str:
    s = str(val).strip()
    return "" if s in ("nan", "None") else s


def _safe_num(val) -> str:
    """数値をstr、空・nanは空文字"""
    try:
        v = str(val).strip()
        if not v or v in ("nan", "None"):
            return ""
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except (ValueError, TypeError):
        return ""


def _safe_datetime(val) -> str:
    """
    日時を文字列化（No Limit → 空文字）
    '2026/4/18 17:58' → そのまま保持（シートに貼れる形式）
    """
    s = str(val).strip()
    if s in ("nan", "None", "No Limit", "NoLimit", ""):
        return ""
    return s


def convert_excel_to_unified(
    excel_path: str,
    sheet_name: str = "広告",
) -> pd.DataFrame:
    """
    TikTok広告エクスポートExcelファイルを統合シート形式のDataFrameに変換する。
    列名がシートと同じのため、ほぼ直接コピーで完了。

    Args:
        excel_path: Excelファイルのパス
        sheet_name: Excelのシート名（デフォルト: '広告'）

    Returns:
        統合シート形式のDataFrame
    """
    from .sheets import COLUMN_NAMES

    logger.info(f"Excelインポート開始: {excel_path}")
    df_src = pd.read_excel(excel_path, sheet_name=sheet_name)
    logger.info(f"読み込み完了: {len(df_src)}行 × {len(df_src.columns)}列")

    rows = []
    for _, row in df_src.iterrows():

        # ── ID列: 'id:xxx' → 'xxx' に変換 ──
        camp_id  = _strip_id_prefix(row.get("キャンペーンID", ""))
        ag_id    = _strip_id_prefix(row.get("広告セット ID", ""))
        ad_id    = _strip_id_prefix(row.get("広告ID", ""))
        identity_id = _strip_id_prefix(row.get("アイデンティティID", ""))

        # ── 日時列: No Limit → 空文字 ──
        start_time = _safe_datetime(row.get("開始時刻", ""))
        end_time   = _safe_datetime(row.get("終了時刻", ""))

        # ── 数値列 ──
        camp_budget  = _safe_num(row.get("キャンペーン予算", ""))
        ag_budget    = _safe_num(row.get("広告セット予算", ""))
        bid          = _safe_num(row.get("入札", ""))
        freq         = _safe_num(row.get("フリークエンシー上限", ""))
        pixel_event  = _safe_num(row.get("ピクセルイベント", ""))

        # ── ロケーション: 'L1234,...' → '1234,...' ──
        loc_raw = _safe_str(row.get("ロケーション", ""))
        location = ",".join(
            p.strip().lstrip("L")
            for p in loc_raw.split(",")
            if p.strip() and p.strip() not in ("nan", "None")
        ) if loc_raw else ""

        # ── ステータス: 既存IDがあれば skipped ──
        status = "skipped" if ad_id else ""

        # ── 直接コピーする列（エクスポートとシートで列名が同じ） ──
        unified_row = {
            # キャンペーン
            "キャンペーン名":         _safe_str(row.get("キャンペーン名", "")),
            "目的":                   _safe_str(row.get("目的", "")),
            "キャンペーン予算タイプ": _safe_str(row.get("キャンペーン予算タイプ", "")),
            "キャンペーン予算":       camp_budget,
            # 広告グループ
            "広告セット名":           _safe_str(row.get("広告セット名", "")),
            "プレースメントタイプ":   _safe_str(row.get("プレースメントタイプ", "")),
            "プレースメント":         _safe_str(row.get("プレースメント", "")),
            "TikTok ピクセル ID":    _safe_str(row.get("TikTok ピクセル ID", "")),
            "ピクセルイベント":       pixel_event,
            "ユーザーリスト設定ID":   _safe_str(row.get("ユーザーリスト設定ID", "")),
            "ユーザーリスト除外ID":   _safe_str(row.get("ユーザーリスト除外ID", "")),
            "ロケーション":           location,
            "性別":                   _safe_str(row.get("性別", "")),
            "年齢":                   _safe_str(row.get("年齢", "")),
            "言語":                   _safe_str(row.get("言語", "")),
            "広告セット予算タイプ":   _safe_str(row.get("広告セット予算タイプ", "")),
            "広告セット予算":         ag_budget,
            "開始時刻":               start_time,
            "終了時刻":               end_time,
            "最適化の目標":           _safe_str(row.get("最適化の目標", "")),
            "課金イベント":           _safe_str(row.get("課金イベント", "")),
            "入札タイプ":             _safe_str(row.get("入札タイプ", "")),
            "入札":                   bid,
            "フリークエンシー上限":   freq,
            # 広告
            "広告名":                 _safe_str(row.get("広告名", "")),
            "広告フォーマット":       _safe_str(row.get("広告フォーマット", "")),
            "動画名":                 _safe_str(row.get("動画名", "")),
            "Google Drive動画URL":    "",   # エクスポートには含まれないため空欄
            "テキスト":               _safe_str(row.get("テキスト", "")),
            "CTAタイプ":              _safe_str(row.get("CTAタイプ", "")),
            "Web URL":                _safe_str(row.get("Web URL", "")),
            "アイデンティティタイプ": _safe_str(row.get("アイデンティティタイプ", "")),
            "アイデンティティID":     identity_id,
            "インプレッショントラッキング URL": _safe_str(row.get("インプレッショントラッキング URL", "")),
            "クリックトラッキングURL": _safe_str(row.get("クリックトラッキングURL", "")),
            # 結果
            "ステータス":             status,
            "キャンペーンID":         camp_id,
            "広告セット ID":          ag_id,
            "広告ID":                 ad_id,
            "エラー内容":             "",
        }
        rows.append(unified_row)

    df_out = pd.DataFrame(rows, columns=COLUMN_NAMES)
    logger.success(f"✅ 変換完了: {len(df_out)}行")
    return df_out


def write_to_sheet(
    df: pd.DataFrame,
    spreadsheet_url: str,
    credentials_dict: dict,
    append: bool = False,
):
    """
    変換済み DataFrame をスプレッドシートに書き込む。

    Args:
        df: convert_excel_to_unified() の戻り値
        spreadsheet_url: スプレッドシートURL
        credentials_dict: GCPサービスアカウント認証情報
        append: True → 既存データの後ろに追加 / False → クリアして上書き
    """
    from .sheets import GoogleSheetsManager

    gsm = GoogleSheetsManager(spreadsheet_url, credentials_dict)
    ws = gsm._worksheet()

    if not append:
        # ヘッダー行（1行目）を残してデータ行をクリア
        total_rows = ws.row_count
        if total_rows > 1:
            ws.delete_rows(2, total_rows)
        logger.info("既存データ行をクリアしました")

    # DataFrame → リスト形式で書き込み（NaN → 空文字）
    data = df.fillna("").values.tolist()
    data = [
        [str(v).strip() if str(v).strip() not in ("nan", "None") else "" for v in row]
        for row in data
    ]

    if data:
        existing_rows = len(ws.get_all_values())
        start_row = existing_rows + 1
        ws.insert_rows(data, row=start_row, value_input_option="RAW")
        logger.success(f"✅ スプレッドシートに{len(data)}行書き込みました")
    else:
        logger.warning("書き込むデータがありません")
