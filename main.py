"""
TikTok Ads Bulk Manager - メインエントリーポイント
"""

import sys
from loguru import logger
from rich.console import Console
from rich.table import Table

from tiktok_api.auth import TikTokAuth
from tiktok_api.business import BusinessManager

console = Console()


def cmd_auth(bc_name: str):
    """OAuthフローを実行してトークンを取得"""
    auth = TikTokAuth()
    auth.run_oauth_flow(bc_name=bc_name)


def cmd_add_bc(bc_id: str, bc_name: str):
    """ビジネスセンターを登録"""
    auth = TikTokAuth()
    auth.add_business_center(bc_id=bc_id, bc_name=bc_name)


def cmd_list_accounts():
    """広告アカウント一覧を表示"""
    auth = TikTokAuth()
    bm = BusinessManager(auth)
    accounts = bm.list_ad_accounts()

    table = Table(title="広告アカウント一覧")
    table.add_column("BC名", style="cyan")
    table.add_column("広告アカウントID", style="green")
    table.add_column("アカウント名")
    table.add_column("ステータス")

    for a in accounts:
        table.add_row(
            a.get("bc_name", ""),
            a.get("advertiser_id", ""),
            a.get("name", ""),
            a.get("status", ""),
        )
    console.print(table)


def cmd_fetch_accounts(bc_name: str):
    """APIから広告アカウント一覧を取得してYAMLに保存"""
    auth = TikTokAuth()
    bm = BusinessManager(auth)
    bm.fetch_ad_accounts(bc_name=bc_name)


def cmd_check_tokens():
    """全BCのトークン状態を確認"""
    auth = TikTokAuth()
    bm = BusinessManager(auth)
    bm.check_all_tokens()


def print_usage():
    console.print("""
[bold]TikTok Ads Bulk Manager[/bold]

使い方:
  python main.py auth <BC名>                  # OAuth認証を実行
  python main.py add-bc <BC_ID> <BC名>        # BCを登録
  python main.py fetch-accounts <BC名>        # 広告アカウントを取得
  python main.py list-accounts               # 広告アカウント一覧
  python main.py check-tokens                # トークン状態確認
""")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print_usage()
        sys.exit(0)

    cmd = args[0]

    if cmd == "auth" and len(args) >= 2:
        cmd_auth(args[1])
    elif cmd == "add-bc" and len(args) >= 3:
        cmd_add_bc(args[1], args[2])
    elif cmd == "fetch-accounts" and len(args) >= 2:
        cmd_fetch_accounts(args[1])
    elif cmd == "list-accounts":
        cmd_list_accounts()
    elif cmd == "check-tokens":
        cmd_check_tokens()
    else:
        print_usage()
