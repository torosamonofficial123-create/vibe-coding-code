import os
import sys

# なぜ: RenderのLive Tailログに、プロセスの終了理由やエラー出力をバッファリングせず完全にリアルタイムで流し込みます。
sys.stdout.reconfigure(line_buffering=True, write_through=True)
sys.stderr.reconfigure(line_buffering=True, write_through=True)

print("🧪 [初期化] スクリプトの実行を開始しました。", flush=True)

import asyncio
import random
import traceback
from dotenv import load_dotenv
import discord
import discord.state
from aiohttp import web

try:
    import discord.commands as abc_commands
    SlashCommandClass = getattr(abc_commands, "SlashCommand", None)
    print("📦 [インポート成功] discord.commands.SlashCommand クラスを特定しました。", flush=True)
except (ImportError, AttributeError) as e:
    SlashCommandClass = None
    print(f"❌ [インポートエラー] クラス抽出に失敗しました: {e}", file=sys.stderr, flush=True)


# ==========================================
# 0. モンキーパッチ
# ==========================================
def completely_replaced_parse_ready_supplemental(self, data):
    print("🛠️ [パッチログ] parse_ready_supplemental を検知。安全化を適用。", flush=True)
    self.pending_payments = {}
    if not hasattr(self, '_presences'):
        self._presences = {}
    return None

discord.state.ConnectionState.parse_ready_supplemental = completely_replaced_parse_ready_supplemental


# ==========================================
# 1. 環境変数の読み込みと入力バリデーション
# ==========================================
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID_STR = os.getenv("TARGET_CHANNEL_ID")
PORT_STR = os.getenv("PORT", "10000")

if not TOKEN:
    print("❌ エラー: DISCORD_TOKEN が設定されていません。", file=sys.stderr, flush=True)
    sys.exit(1)

try:
    if not CHANNEL_ID_STR:
        raise ValueError("TARGET_CHANNEL_ID が設定されていません。")
    TARGET_CHANNEL_ID = int(CHANNEL_ID_STR)
    PORT = int(PORT_STR)
except ValueError as e:
    print(f"❌ バリデーションエラー: {e}", file=sys.stderr, flush=True)
    sys.exit(1)


# ==========================================
# 2. コマンド設定
# ==========================================
COMMANDS_QUEUE = [
    {
        "bot_id": 761562078095867916, 
        "name": "up", 
        "command_id": "1363739182672904354", 
        "version": "1464492483328081983", 
        "interval": 7200
    },
    {
        "bot_id": 903541413298450462, 
        "name": "up", 
        "command_id": "935190259111706754",
        "version": "1051208009747021914",
        "interval": 3600
    },
    {
        "bot_id": 981314695543783484, 
        "name": "up", 
        "command_id": "1135405664852783157",
        "version": "1436546810205442153",
        "interval": 3600
    },
    {
        "bot_id": 302050872383242240, 
        "name": "bump", 
        "command_id": "947088344167366698",
        "version": "1051151064008769576",
        "interval": 7200
    }
]


# ==========================================
# 3. ボットクライアントの初期化とタスク管理
# ==========================================
bot = discord.Client()

async def run_single_command_loop(channel, cmd_info, initial_delay):
    bot_id = cmd_info["bot_id"]
    cmd_name = cmd_info["name"]
    cmd_id = cmd_info["command_id"]
    cmd_version = cmd_info["version"]
    base_delay = cmd_info["interval"]

    # なぜ: 起動直後に全タスクが一斉に同一チャンネルへリクエストを投げると、
    # ゲートウェイのイベント詰まりやレートリミットを誘発するため、タスクごとに個別の初期遅延を挟みます。
    if initial_delay > 0:
        print(f"⏳ [初期分散待機] Bot ID: {bot_id} は送信衝突を避けるため {initial_delay} 秒待機します...", flush=True)
        await asyncio.sleep(initial_delay)

    try:
        print(f"📡 [ダイレクトアプローチ] Bot ID: {bot_id} の '/{cmd_name}' を実体化ビルドします...", flush=True)
        
        if SlashCommandClass is None:
            raise AttributeError("discord.commands.SlashCommand クラス定義がロードされていません。")

        payload = {
            "id": str(cmd_id),
            "application_id": str(bot_id),
            "version": str(cmd_version),
            "name": cmd_name,
            "description": "Auto generated mobile command syntax",
            "type": 1,
            "options": [],
            "dm_permission": True,
            "contexts": [0, 1, 2]
        }
        
        state = bot._connection
        target_command = SlashCommandClass(state=state, data=payload)
        print(f"🎯 [ビルド成功] 具象コマンドオブジェクトの復元に成功: /{cmd_name} (ID: {cmd_id})", flush=True)

        while True:
            print(f"⚡ [送信直前] チャンネルへ '/{cmd_name}' を投入します... (Bot: {bot_id})", flush=True)
            try:
                # なぜ: discord.py-self の内部実装はコマンド送信HTTPリクエスト直後に `wait_for('interaction_finish')` 
                # 等によりDiscordからの応答パケット受信を3秒間同期追跡します。ログが示す通り、Discord側の反映遅延や
                # 複数同時送信によってこのイベント受信がタイムアウトすると `InvalidData` 例外が上がります。
                # しかし、HTTPリクエスト自体はすでにDiscordへ到達して処理が通過しているため、この例外は安全に捕捉・無視して
                # ループを維持させる必要があります。
                res = await target_command(channel)
                print(f"✨ [送信成功ログ] '/{cmd_name}' (Bot: {bot_id}) の応答を受信。応答: {res}", flush=True)
            except discord.errors.InvalidData as e:
                print(f"⚠️ [応答タイムアウト警告] '/{cmd_name}' (Bot: {bot_id}) の送信完了後のイベント応答が時間内に返されませんでした（パケット自体は送信されています）: {e}", flush=True)
            except discord.errors.HTTPException as http_err:
                print(f"🛑 [HTTPエラー] APIリクエスト自体が拒否されました (Bot: {bot_id}): {http_err}", file=sys.stderr, flush=True)

            # 次回送信までのインターバル計算
            yuragi = random.uniform(5.0, 15.0)
            total_delay = base_delay + yuragi
            print(f"⏳ [待機スケジュール] 次の送信まで {total_delay:.2f} 秒待機します (Bot: {bot_id})", flush=True)
            await asyncio.sleep(total_delay)

    except Exception as e:
        print(f"🚨 [致命的エラー] ループが完全に破壊されました (Bot: {bot_id}): {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)


async def startup_automation_task():
    print("⏳ [独立自動タスク] 起動完了。セッション安定化のため20秒間待機します...", flush=True)
    
    for i in range(20):
        await asyncio.sleep(1.0)
        if i % 10 == 0:
            print(f"⏳ [独立自動タスク] 接続待機中... ({i}/20秒)", flush=True)

    print(f"🔍 [独立自動タスク] ターゲットチャンネル ID: {TARGET_CHANNEL_ID} のフェッチを実行します...", flush=True)
    try:
        channel = await bot.fetch_channel(TARGET_CHANNEL_ID)
        print(f"📂 [ターゲット特定] 配信先チャンネルの捕捉に成功: #{getattr(channel, 'name', '不明')} (ID: {channel.id})", flush=True)
    except Exception as e:
        print(f"🛑 [独立自動タスク・エラー] チャンネルのフェッチに失敗しました: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return

    print("🔄 各コマンドの送信タスクを時間差でイベントループに投入します...", flush=True)
    # なぜ: 初期送信のタイミングを意図的に 10 秒ずつずらし、同一時間帯に `wait_for` の追跡スレッドが
    # 複数競合してイベントを食い合う現象、および Discord API からのスパム判定を防御します。
    for index, cmd_info in enumerate(COMMANDS_QUEUE):
        delay = index * 10
        asyncio.create_task(run_single_command_loop(channel, cmd_info, delay))


# ==========================================
# 4. Webサーバーとメインルーチン
# ==========================================
async def handle_health_check(request):
    return web.Response(text="Bot is running smoothly", status=200)

async def main():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 接続待ち受けを開始します (Port: {PORT})。ヘルスチェック準備完了。", flush=True)

    print("🔌 [タスク登録] Discord 接続タスクをイベントループに投入...", flush=True)
    asyncio.create_task(bot.start(TOKEN))
    
    print("🔌 [タスク登録] 自動コマンド配備タスクをイベントループに投入...", flush=True)
    asyncio.create_task(startup_automation_task())
    
    print("📢 すべての非同期コルーチンが起動しました。永続スリープに入ります。", flush=True)
    
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("プログラムが手動で終了されました。", flush=True)
