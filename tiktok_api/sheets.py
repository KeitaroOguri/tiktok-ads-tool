"""
Google Sheets連携 - 統合シート（TikTokエクスポート形式準拠・日本語プルダウン対応）
"""

from __future__ import annotations
from typing import Optional
from loguru import logger
import pandas as pd


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_NAME = "入稿データ"

SECTION_COLORS = {
    "campaign": {"red": 0.67, "green": 0.84, "blue": 0.90},  # 水色
    "adgroup":  {"red": 0.72, "green": 0.88, "blue": 0.70},  # 緑
    "ad":       {"red": 1.00, "green": 0.90, "blue": 0.60},  # 黄
    "result":   {"red": 0.85, "green": 0.85, "blue": 0.85},  # グレー
}

SECTION_LABELS = {
    "campaign": "📁 キャンペーン",
    "adgroup":  "📂 広告グループ（広告セット）",
    "ad":       "📄 広告",
    "result":   "📊 結果（自動入力）",
}

# 必須項目のヘッダー文字色（赤）
REQUIRED_TEXT_COLOR = {"red": 0.80, "green": 0.00, "blue": 0.00}
NORMAL_TEXT_COLOR   = {"red": 0.10, "green": 0.10, "blue": 0.10}

# -------------------------------------------------------
# 統合シートの列定義
# required=True → ヘッダーを赤文字
# options → プルダウン（Noneの場合は動的に外から設定）
# -------------------------------------------------------
UNIFIED_COLUMNS: list[dict] = [

    # ━━━ キャンペーン ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "name": "キャンペーン名",
        "section": "campaign",
        "width": 220,
        "required": True,
    },
    {
        "name": "目的",
        "section": "campaign",
        "width": 160,
        "required": True,
        "options": [
            "コンバージョン", "トラフィック", "リーチ", "動画視聴",
            "アプリインストール", "リード獲得", "フォロワー獲得",
        ],
        "note": "コンバージョン=Sales / トラフィック=Traffic\n動画視聴=Video Views / アプリインストール=App Installs",
    },
    {
        "name": "キャンペーン予算タイプ",
        "section": "campaign",
        "width": 170,
        "required": True,
        "options": ["日予算", "総予算", "無制限"],
        "note": "日予算=Daily / 総予算=Lifetime / 無制限=No Limit",
    },
    {
        "name": "キャンペーン予算",
        "section": "campaign",
        "width": 130,
        "note": "予算タイプが「無制限」の場合は空欄でOK（単位: 円）",
    },

    # ━━━ 広告グループ（広告セット） ━━━━━━━━━━━━━━━━━━
    {
        "name": "広告セット名",
        "section": "adgroup",
        "width": 220,
        "required": True,
    },
    {
        "name": "プレースメントタイプ",
        "section": "adgroup",
        "width": 160,
        "options": ["自動", "手動"],
        "note": "自動=Automatic（推奨） / 手動=Select",
    },
    {
        "name": "プレースメント",
        "section": "adgroup",
        "width": 160,
        "note": "手動のときのみ入力\n例: TikTok, Pangle",
    },
    {
        "name": "TikTok ピクセル ID",
        "section": "adgroup",
        "width": 240,
        "note": (
            "連携済みピクセルをプルダウンから選択\n"
            "形式: 「ピクセル名 [pixel_id]」\n"
            "コンバージョン計測を使う場合は必須"
        ),
        # options は initialize_template で動的にセット
    },
    {
        "name": "ピクセルイベント",
        "section": "adgroup",
        "width": 130,
        "note": "ピクセルのイベントコード（数値）\n例: 96 = CompletePayment（購入完了）",
    },
    {
        "name": "ユーザーリスト設定ID",
        "section": "adgroup",
        "width": 180,
        "note": "カスタムオーディエンスID（カンマ区切りで複数可）",
    },
    {
        "name": "ユーザーリスト除外ID",
        "section": "adgroup",
        "width": 180,
        "note": "除外オーディエンスID（カンマ区切りで複数可）",
    },
    {
        "name": "ロケーション",
        "section": "adgroup",
        "width": 200,
        "note": (
            "地域IDをカンマ区切りで入力（Lプレフィックス不要）\n"
            "例: 1865694,1864226,...\n"
            "空欄 = 日本（7709）を自動セット"
        ),
    },
    {
        "name": "性別",
        "section": "adgroup",
        "width": 100,
        "options": ["すべて", "男性", "女性"],
    },
    {
        "name": "年齢",
        "section": "adgroup",
        "width": 180,
        "note": (
            "年齢層をカンマ区切りで入力\n"
            "例: 18-24,25-34,35-44\n"
            "All または空欄 = すべての年齢"
        ),
    },
    {
        "name": "言語",
        "section": "adgroup",
        "width": 100,
        "note": "言語コード（例: ja=日本語, en=英語）\n空欄 = すべての言語",
    },
    {
        "name": "広告セット予算タイプ",
        "section": "adgroup",
        "width": 170,
        "options": ["日予算", "総予算", "無制限"],
        "note": "空欄 = 無制限（キャンペーン予算に従う）",
    },
    {
        "name": "広告セット予算",
        "section": "adgroup",
        "width": 130,
        "note": "広告グループレベルの予算（単位: 円）\n空欄 = キャンペーン予算に従う",
    },
    {
        "name": "開始時刻",
        "section": "adgroup",
        "width": 180,
        "note": "形式: 2024/4/1 0:00 または 2024-04-01 00:00:00\n空欄 = 入稿時刻を自動セット",
    },
    {
        "name": "終了時刻",
        "section": "adgroup",
        "width": 180,
        "note": "形式: 2024/7/31 23:59\nNo Limit または空欄 = 終了なし",
    },
    {
        "name": "最適化の目標",
        "section": "adgroup",
        "width": 160,
        "options": ["コンバージョン", "クリック", "リーチ", "動画再生", "フォロー", "インプレッション"],
    },
    {
        "name": "課金イベント",
        "section": "adgroup",
        "width": 120,
        "required": True,
        "options": ["oCPM", "CPM", "CPC", "CPV"],
        "note": "oCPM=最適化インプレッション / CPM=インプレッション\nCPC=クリック / CPV=動画再生",
    },
    {
        "name": "入札タイプ",
        "section": "adgroup",
        "width": 160,
        "required": True,
        "options": ["自動入札", "コストキャップ", "入札キャップ"],
        "note": "自動入札=Lowest Cost（入札額不要）\nコストキャップ/入札キャップ=手動（入札額必須）",
    },
    {
        "name": "入札",
        "section": "adgroup",
        "width": 100,
        "note": "コストキャップ/入札キャップのときのみ入力（単位: 円）",
    },
    {
        "name": "フリークエンシー上限",
        "section": "adgroup",
        "width": 150,
        "note": "1ユーザーへの最大表示回数（例: 2）",
    },

    # ━━━ 広告 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "name": "広告名",
        "section": "ad",
        "width": 200,
        "required": True,
    },
    {
        "name": "広告フォーマット",
        "section": "ad",
        "width": 140,
        "required": True,
        "options": ["単一動画", "画像", "スパーク広告"],
    },
    {
        "name": "動画名",
        "section": "ad",
        "width": 200,
        "note": (
            "TikTokクリエイティブライブラリの動画名\n"
            "新規アップロードは「Google Drive動画URL」を使用"
        ),
    },
    {
        "name": "Google Drive動画URL",
        "section": "ad",
        "width": 260,
        "note": (
            "Google DriveのファイルURL（動画名が空の場合に自動アップロード）\n"
            "例: https://drive.google.com/file/d/xxxxx/view\n"
            "⚠️ サービスアカウントとファイルを共有してください:\n"
            "tiktok-ads-tool@winged-vigil-371710.iam.gserviceaccount.com"
        ),
    },
    {
        "name": "テキスト",
        "section": "ad",
        "width": 260,
        "note": "広告のキャプションテキスト（絵文字OK）",
    },
    {
        "name": "CTAタイプ",
        "section": "ad",
        "width": 180,
        "options": [
            "詳しくはこちら", "今すぐ購入", "アプリをダウンロード",
            "今すぐ申し込む", "今すぐ予約", "お問い合わせ",
            "今すぐ登録", "今すぐ視聴", "今すぐプレイ",
            "詳細を見る", "今すぐ注文", "今すぐ入手",
            "ダイナミック（自動）",
        ],
        "note": "ダイナミック（自動）= TikTokが最適なCTAを自動選択",
    },
    {
        "name": "Web URL",
        "section": "ad",
        "width": 280,
        "note": "ランディングページURL\n例: https://example.com/?ttclid=__CLICKID__",
    },
    {
        "name": "アイデンティティタイプ",
        "section": "ad",
        "width": 180,
        "options": ["BC認証済みTikTok", "カスタムユーザー", "認証コード"],
        "note": "BC認証済みTikTok = TTBC Authorized Post（最も一般的）",
    },
    {
        "name": "アイデンティティID",
        "section": "ad",
        "width": 260,
        "note": (
            "連携済みTikTokアカウントをプルダウンから選択\n"
            "形式: 「アカウント名 [identity_id]」"
        ),
        # options は initialize_template で動的にセット
    },
    {
        "name": "インプレッショントラッキング URL",
        "section": "ad",
        "width": 260,
        "note": "インプレッション計測用サードパーティトラッキングURL（省略可）",
    },
    {
        "name": "クリックトラッキングURL",
        "section": "ad",
        "width": 260,
        "note": "クリック計測用サードパーティトラッキングURL（省略可）",
    },

    # ━━━ 結果（自動入力） ━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "name": "ステータス",
        "section": "result",
        "width": 110,
        "note": "入稿後に自動入力: success / skipped / error",
    },
    {
        "name": "キャンペーンID",
        "section": "result",
        "width": 180,
        "note": "入稿後に自動入力。既存IDを書いておくと再作成をスキップ",
    },
    {
        "name": "広告セット ID",
        "section": "result",
        "width": 180,
        "note": "入稿後に自動入力。既存IDを書いておくと再作成をスキップ",
    },
    {
        "name": "広告ID",
        "section": "result",
        "width": 180,
        "note": "入稿後に自動入力。既存IDを書いておくと再入稿をスキップ",
    },
    {
        "name": "エラー内容",
        "section": "result",
        "width": 300,
        "note": "エラーが発生した場合のメッセージ",
    },
]

COLUMN_NAMES = [c["name"] for c in UNIFIED_COLUMNS]


class GoogleSheetsManager:

    def __init__(self, spreadsheet_url: str, credentials_dict: dict):
        self.spreadsheet_url = spreadsheet_url
        self.credentials_dict = credentials_dict
        self._gc = None
        self._ss = None

    def _client(self):
        if self._gc is None:
            try:
                import gspread
                from google.oauth2.service_account import Credentials
            except ImportError:
                raise ImportError("pip install gspread google-auth が必要です")
            creds = Credentials.from_service_account_info(
                self.credentials_dict, scopes=SCOPES
            )
            self._gc = gspread.authorize(creds)
        return self._gc

    def _spreadsheet(self):
        if self._ss is None:
            self._ss = self._client().open_by_url(self.spreadsheet_url)
        return self._ss

    def _worksheet(self, create: bool = False):
        ss = self._spreadsheet()
        try:
            return ss.worksheet(SHEET_NAME)
        except Exception:
            if create:
                return ss.add_worksheet(
                    title=SHEET_NAME,
                    rows=1000,
                    cols=len(UNIFIED_COLUMNS) + 5,
                )
            raise

    # -------------------------------------------------------
    # テンプレート初期化
    # -------------------------------------------------------

    def initialize_template(
        self,
        pixel_options: list[str] | None = None,
        identity_id_options: list[str] | None = None,
    ):
        """
        統合シートを完全リセットして再作成。

        Args:
            pixel_options: ["ピクセル名 [pixel_id]", ...] TikTok APIから取得
            identity_id_options: ["アカウント名 [identity_id]", ...] TikTok APIから取得
        """
        ss = self._spreadsheet()

        # ── シートの取得または作成 ──
        try:
            ws = ss.worksheet(SHEET_NAME)
            logger.info(f"既存シートを完全リセット: {SHEET_NAME}")
        except Exception:
            ws = ss.add_worksheet(
                title=SHEET_NAME,
                rows=1000,
                cols=len(UNIFIED_COLUMNS) + 5,
            )
            logger.info(f"シート新規作成: {SHEET_NAME}")

        sheet_id = ws.id

        # ── 列定義に動的オプションをマージ ──
        col_defs = []
        for col in UNIFIED_COLUMNS:
            col_copy = dict(col)
            if col["name"] == "TikTok ピクセル ID" and pixel_options:
                col_copy["options"] = pixel_options
            if col["name"] == "アイデンティティID" and identity_id_options:
                col_copy["options"] = identity_id_options
            col_defs.append(col_copy)

        # ── 全操作を1回のbatch_updateに統合（API呼び出し回数を最小化） ──
        requests = []

        # [1] シート全体クリア（値・書式・バリデーション）
        requests.append({
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1000,
                    "startColumnIndex": 0,
                    "endColumnIndex": 200,
                },
                "fields": "userEnteredValue,userEnteredFormat,dataValidation,note",
            }
        })

        # [2] ヘッダー行の値をセット
        requests.append({
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(col_defs),
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": col["name"]}}
                        for col in col_defs
                    ]
                }],
                "fields": "userEnteredValue",
            }
        })

        # [3] 各列の書式・バリデーション・列幅・メモ
        for col_idx, col_def in enumerate(col_defs):
            section    = col_def["section"]
            color      = SECTION_COLORS[section]
            required   = col_def.get("required", False)
            text_color = REQUIRED_TEXT_COLOR if required else NORMAL_TEXT_COLOR
            note_text  = col_def.get("note", "")

            # ヘッダーセルの書式（必須=赤文字）+ メモ
            header_cell: dict = {
                "userEnteredFormat": {
                    "backgroundColor": color,
                    "textFormat": {
                        "bold": True,
                        "fontSize": 10,
                        "foregroundColor": text_color,
                    },
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "wrapStrategy": "WRAP",
                },
            }
            header_fields = "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)"
            if note_text:
                header_cell["note"] = note_text
                header_fields += ",note"

            requests.append({
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": col_idx,
                        "endColumnIndex": col_idx + 1,
                    },
                    "rows": [{"values": [header_cell]}],
                    "fields": header_fields,
                }
            })

            # データ行の背景色（薄め）
            data_color = {k: min(1.0, 0.93 + v * 0.07) for k, v in color.items()}
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": col_idx,
                        "endColumnIndex": col_idx + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {"backgroundColor": data_color}
                    },
                    "fields": "userEnteredFormat(backgroundColor)",
                }
            })

            # プルダウン設定
            opts = [o for o in col_def.get("options", []) if o and o != ""]
            if opts:
                requests.append({
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": col_idx,
                            "endColumnIndex": col_idx + 1,
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [{"userEnteredValue": v} for v in opts],
                            },
                            "showCustomUi": True,
                            "strict": False,
                        },
                    }
                })

            # 列幅
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": col_idx,
                        "endIndex": col_idx + 1,
                    },
                    "properties": {"pixelSize": col_def.get("width", 140)},
                    "fields": "pixelSize",
                }
            })

        # [4] ヘッダー行を固定
        requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        })

        # ── 1回のAPIコールで全操作を完了 ──
        ss.batch_update({"requests": requests})
        logger.info(f"batch_update完了: {len(requests)}件のリクエスト")

        logger.success(f"✅ テンプレートシート初期化完了: {SHEET_NAME} ({len(COLUMN_NAMES)}列)")

    # -------------------------------------------------------
    # 読み込み
    # -------------------------------------------------------

    def read_data(self) -> pd.DataFrame:
        ws = self._worksheet()
        records = ws.get_all_records(expected_headers=COLUMN_NAMES)
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=COLUMN_NAMES)
        non_empty = df.apply(lambda row: row.astype(str).str.strip().any(), axis=1)
        df = df[non_empty].reset_index(drop=True)
        logger.info(f"データ読み込み: {len(df)}行")
        return df

    # -------------------------------------------------------
    # 結果書き戻し
    # -------------------------------------------------------

    def write_results(self, results: list[dict]):
        if not results:
            return

        import gspread

        ws = self._worksheet()
        headers = ws.row_values(1)

        def col_of(name: str) -> Optional[int]:
            try:
                return headers.index(name) + 1
            except ValueError:
                return None

        col_status  = col_of("ステータス")
        col_camp_id = col_of("キャンペーンID")
        col_ag_id   = col_of("広告セット ID")
        col_ad_id   = col_of("広告ID")
        col_err     = col_of("エラー内容")
        col_video   = col_of("動画名")

        cells: list[gspread.Cell] = []
        for r in results:
            sheet_row = r["row_index"] + 1
            if col_status:
                cells.append(gspread.Cell(sheet_row, col_status, r.get("status", "")))
            if col_camp_id:
                cells.append(gspread.Cell(sheet_row, col_camp_id, r.get("campaign_id", "")))
            if col_ag_id:
                cells.append(gspread.Cell(sheet_row, col_ag_id, r.get("adgroup_id", "")))
            if col_ad_id:
                cells.append(gspread.Cell(sheet_row, col_ad_id, r.get("ad_id", "")))
            if col_err:
                cells.append(gspread.Cell(sheet_row, col_err, r.get("error", "")))
            if col_video and r.get("video_id"):
                cells.append(gspread.Cell(sheet_row, col_video, r.get("video_id", "")))

        if cells:
            ws.update_cells(cells, value_input_option="RAW")
            logger.success(f"✅ 結果書き戻し完了: {len(results)}行")
