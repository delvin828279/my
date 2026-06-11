import requests
from bs4 import BeautifulSoup
import json
import random
import socket
import os
import asyncio
import schedule
import time
import threading
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import datetime

# ─── تنظیمات ───────────────────────────────────────────
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "YOUR_CHANNEL_ID_HERE")
SEND_INTERVAL_MINUTES = 5

# منابع دریافت پروکسی تلگرام و کانفیگ‌های Vless
SOURCES = {
    'mtproto_bolt': 'https://proxybolt.link/',
    'mtproto_github': [
        f"https://raw.githubusercontent.com/V2RAYCONFIGSPOOL/TELEGRAM_PROXY_SUB/refs/heads/main/telegram_proxy_no{i}.txt"
        for i in range(1, 6) # ۵ منبع اول برای بهینه‌سازی سرعت و مصرف رم
    ],
    'vless_github': [
        "https://raw.githubusercontent.com/DeX7eR-0/V2RAY-CONFIGS/main/All_Configs_Sub.txt",
        "https://raw.githubusercontent.com/mohammadw9/FreeV2rayConfigs/main/vless.txt"
    ]
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

COUNTRY_FLAGS = {
    "United States": "🇺🇸", "Germany": "🇩🇪", "Netherlands": "🇳🇱",
    "France": "🇫🇷", "United Kingdom": "🇬🇧", "Canada": "🇨🇦",
    "Singapore": "🇸🇬", "Japan": "🇯🇵", "Russia": "🇷🇺",
    "Turkey": "🇹🇷", "Finland": "🇫🇮", "Sweden": "🇸🇪"
}

_geo_cache = {}
_stats = {
    "total_checked": 0,
    "total_active":  0,
    "start_time":    datetime.now(),
}

# بانک اطلاعات حافظه موقت (کَش هوشمند)
_CACHED_MTPROTO = []
_CACHED_VLESS   = []

# ══════════════════════════════════════════════════════════
#  ابزارهای استخراج و ژئولوکیشن
# ══════════════════════════════════════════════════════════

def get_location(host):
    if not host or host.replace('.', '').isdigit() is False:
        # اگر هاست به صورت دامنه بود آی‌پی آن را می‌گیریم
        try: host = socket.gethostbyname(host)
        except: return {"country": "Unknown", "city": "", "flag": "🌍"}
        
    if host in _geo_cache: return _geo_cache[host]
    try:
        r = requests.get(f"http://ip-api.com/json/{host}?fields=country,city", timeout=2)
        d = r.json()
        if d.get('country'):
            country = d['country']
            res = {"country": country, "city": d.get('city', ''), "flag": COUNTRY_FLAGS.get(country, '🌍')}
            _geo_cache[host] = res
            return res
    except: pass
    return {"country": "Unknown", "city": "", "flag": "🌍"}

def escape_md(text):
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = str(text).replace(ch, f'\\{ch}')
    return text

def parse_vless_host(config_link):
    try:
        # استخراج هاست و پورت از لینک vless
        server_part = config_link.split('@')[1]
        host_port = server_part.split('?')[0].split('#')[0]
        host = host_port.split(':')[0]
        port = host_port.split(':')[1] if ':' in host_port else "443"
        return host, port
    except:
        return None, None

# ══════════════════════════════════════════════════════════
#  تست با Check-Host (بدون قفل کردن سرور)
# ══════════════════════════════════════════════════════════

IRAN_NODES = ["ir1.node.check-host.net", "ir4.node.check-host.net"]

def check_iran_connection(host, port):
    try:
        node = random.choice(IRAN_NODES)
        url = f"https://check-host.net/check-tcp?host={host}:{port}&max_nodes=1&node={node}"
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=4)
        req_id = r.json().get("request_id")
        if not req_id: return None
        time.sleep(2) # زمان انتظار برای پاسخ چک هاست
        res = requests.get(f"https://check-host.net/check-result/{req_id}", timeout=4).json()
        pings = []
        for n_res in res.values():
            if n_res and isinstance(n_res, list):
                for item in n_res:
                    if isinstance(item, dict) and "time" in item: pings.append(int(item["time"] * 1000))
        return min(pings) if pings else None
    except: return None

def test_single_server(item):
    """تست همزمان پینگ ایران برای انواع کانکشن‌ها"""
    host, port = item['host'], item['port']
    ping = check_iran_connection(host, port)
    if ping is not None:
        item['ping'] = ping
        return item
    return None

# ══════════════════════════════════════════════════════════
#  اسکنر منابع و به‌روزرسانی کَش
# ══════════════════════════════════════════════════════════

def update_system_cache():
    global _CACHED_MTPROTO, _CACHED_VLESS, _stats
    print("🔍 شروع اسکن و تست سرورها...")
    
    # --- ۱. جمع‌آوری MTProto ---
    raw_mtproto = []
    # از سایت proxybolt
    try:
        r = requests.get(SOURCES['mtproto_bolt'], headers=HEADERS, timeout=8)
        page_data = json.loads(BeautifulSoup(r.content, 'html.parser').find('div', id='app')['data-page'])
        for p in page_data.get('props', {}).get('proxies', []):
            if p.get('host'):
                link = f"tg://proxy?server={p['host']}&port={p['port']}&secret={p.get('secret','')}"
                raw_mtproto.append({"type": "mtproto", "link": link, "host": p['host'], "port": str(p['port'])})
    except: pass
    # از گیت‌هاب
    for url in SOURCES['mtproto_github']:
        try:
            r = requests.get(url, headers=HEADERS, timeout=4)
            for line in r.text.strip().split('\n'):
                if "server=" in line:
                    p = parse_qs(urlparse(line.strip().replace("https://t.me/proxy", "tg://proxy")).query)
                    if p.get('server'): raw_mtproto.append({"type": "mtproto", "link": line.strip(), "host": p['server'][0], "port": p['port'][0]})
        except: continue

    # --- ۲. جمع‌آوری Vless ---
    raw_vless = []
    for url in SOURCES['vless_github']:
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            matches = re.findall(r'(vless://[^\s]+)', r.text)
            for link in matches:
                host, port = parse_vless_host(link)
                if host: raw_vless.append({"type": "vless", "link": link, "host": host, "port": port})
        except: continue

    # حذف تکراری‌ها و محدود کردن تعداد برای جلوگیری از پر شدن رم آمورا
    unique_mtproto = {f"{x['host']}:{x['port']}": x for x in raw_mtproto}.values()
    unique_vless = {f"{x['host']}:{x['port']}": x for x in raw_vless}.values()
    
    test_list = list(unique_mtproto)[:25] + list(unique_vless)[:25]
    _stats["total_checked"] += len(test_list)

    # تست همزمان با تعداد محدود تِرد (Max_Workers=6) برای امنیت رم سرور
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(test_single_server, test_list))
    
    active_items = [r for r in results if r is not None]
    _stats["total_active"] += len(active_items)

    # تفکیک و اعمال ژئولوکیشن و ذخیره در کَش
    new_mtproto, new_vless = [], []
    for item in active_items:
        geo = get_location(item['host'])
        item.update(geo)
        if item['type'] == "mtproto": new_mtproto.append(item)
        else: new_vless.append(item)

    # مرتب‌سازی بر اساس کمترین پینگ
    new_mtproto.sort(key=lambda x: x['ping'])
    new_vless.sort(key=lambda x: x['ping'])

    _CACHED_MTPROTO = new_mtproto[:10]
    _CACHED_VLESS   = new_vless[:10]
    print(f"✅ کَش بروز شد! MTProto مجاز: {len(_CACHED_MTPROTO)} | Vless مجاز: {len(_CACHED_VLESS)}")

# ══════════════════════════════════════════════════════════
#  فرمت‌ساز پیام‌ها
# ══════════════════════════════════════════════════════════

def format_mtproto_msg(proxies):
    lines = ["🔐 *پروکسی‌های فعال تلگرام \\(MTProto\\)*", "━━━━━━━━━━━━━━━━━━━━\n"]
    for i, p in enumerate(proxies[:5], 1):
        lines.append(f"*{i}\\. {p['flag']} {escape_md(p['country'])}*")
        lines.append(f"⚡ پینگ ایران: `{p['ping']}ms`")
        lines.append(f"[🔗 اتصال به سرور]({p['link']})\n")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

def format_vless_msg(configs):
    lines = ["🚀 *کانفیگ‌های فعال V2ray \\(Vless\\)*", "━━━━━━━━━━━━━━━━━━━━\n"]
    for i, c in enumerate(configs[:3], 1):
        lines.append(f"*{i}\\. {c['flag']} {escape_md(c['country'])}*")
        lines.append(f"⚡ پینگ ایران: `{c['ping']}ms`")
        lines.append(f"📋 برای کپی روی کادر زیر بزنید:")
        lines.append(f"`{escape_md(c['link'])}`\n")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ══════════════════════════════════════════════════════════
#  هندلرها و کیبوردهای شیشه‌ای ربات
# ══════════════════════════════════════════════════════════

def build_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 پروکسی‌های تلگرام", callback_data="show_mtproto"),
         InlineKeyboardButton("🚀 کانفیگ‌های V2ray", callback_data="show_vless")],
        [InlineKeyboardButton("🎲 اتصال شانس (تصادفی)", callback_data="random_connect")],
        [InlineKeyboardButton("📋 کپی یکجای پروکسی‌ها", callback_data="copy_all"),
         InlineKeyboardButton("📊 آمار سرور", callback_data="show_stats")]
    ])

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = "👋 *به ابر\\-ربات هوشمند ضد فیلتر خوش آمدید\\!*\n\nتمام سرورها به صورت شبانه‌روزی تست شده و موارد فیلترشده در ایران خودکار حذف می‌شوند\\."
    await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=build_menu())

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # حل قطعی مشکل تایم‌اوت دکمه
    data = query.data

    if not _CACHED_MTPROTO and not _CACHED_VLESS:
        await query.message.reply_text("⏳ بانک سرورها در حال بارگذاری اولیه است؛ لطفاً ۱ دقیقه دیگر تست کنید\\.")
        return

    if data == "show_mtproto":
        await query.message.reply_text(format_mtproto_msg(_CACHED_MTPROTO), parse_mode="MarkdownV2", disable_web_page_preview=True)
        
    elif data == "show_vless":
        if not _CACHED_VLESS:
            await query.message.reply_text("❌ در حال حاضر کانفیگ Vless سالمی پیدا نشد\\.")
        else:
            await query.message.reply_text(format_vless_msg(_CACHED_VLESS), parse_mode="MarkdownV2")
            
    elif data == "random_connect":
        # انتخاب رندوم از بین بهترین سرورها
        pool = _CACHED_MTPROTO[:3] + _CACHED_VLESS[:3]
        selected = random.choice(pool)
        if selected['type'] == "mtproto":
            txt = f"🎲 *پروکسی شانس شما \\(MTProto\\):*\n\n🌍 کشور: {selected['flag']} {escape_md(selected['country'])}\n⚡ پینگ: `{selected['ping']}ms`\n\n[🔗 برای اتصال فوری کلیک کنید]({selected['link']})"
            await query.message.reply_text(txt, parse_mode="MarkdownV2")
        else:
            txt = f"🎲 *کانفیگ شانس شما \\(Vless\\):*\n\n🌍 کشور: {selected['flag']} {escape_md(selected['country'])}\n⚡ پینگ: `{selected['ping']}ms`\n\n📋 جهت کپی لمس کنید:\n`{escape_md(selected['link'])}`"
            await query.message.reply_text(txt, parse_mode="MarkdownV2")
            
    elif data == "copy_all":
        # ارسال لیست خام برای کپی راحت یکجا
        lines = ["📋 *کپی یکجای لینک‌های فعال برای اشتراک‌گذاری:*\n"]
        for p in _CACHED_MTPROTO[:5]: lines.append(f"`{escape_md(p['link'])}`")
        await query.message.reply_text("\n\n".join(lines), parse_mode="MarkdownV2")
        
    elif data == "show_stats":
        uptime_hours = int((datetime.now() - _stats["start_time"]).total_seconds() // 3600)
        text = f"📊 *وضعیت پایداری ربات آمورا*\n\n🔍 کل سرورهای بررسی شده: `{_stats['total_checked']}`\n✅ سرورهای زنده شناسایی شده: `{_stats['total_active']}`\n⏱ آپتایم سیستم: `{uptime_hours}` ساعت"
        await query.message.reply_text(text, parse_mode="MarkdownV2")

# ══════════════════════════════════════════════════════════
#  زمان‌بند ۲۴ ساعته (Background Thread)
# ══════════════════════════════════════════════════════════

def run_schedule(bot_instance):
    # اجرای اول برای پر شدن کَش به محض روشن شدن ربات
    update_system_cache()
    
    def job():
        update_system_cache()
        # ارسال خودکار به کانال در صورت تنظیم CHANNEL_ID
        if CHANNEL_ID and _CACHED_MTPROTO:
            try:
                asyncio.run(bot_instance.send_message(
                    chat_id=CHANNEL_ID, 
                    text=format_mtproto_msg(_CACHED_MTPROTO) + "\n\n🤖 @YourBotID", 
                    parse_mode="MarkdownV2", 
                    disable_web_page_preview=True
                ))
            except Exception as e: print(f"خطای ارسال به کانال: {e}")

    schedule.every(SEND_INTERVAL_MINUTES).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(10)

# ══════════════════════════════════════════════════════════
#  اجرای اصلی (Main)
# ══════════════════════════════════════════════════════════

def main():
    if not BOT_TOKEN or "YOUR_" in BOT_TOKEN:
        print("❌ خطای توکن! لطفا توکن ربات خود را در متغیرهای محیطی یا کد ست کنید.")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # راه‌اندازی بخش اسکنر در ترد جداگانه دائم‌الکار
    bot_instance = Bot(token=BOT_TOKEN)
    threading.Thread(target=run_schedule, args=(bot_instance,), daemon=True).start()

    print("🚀 ربات چندمنظوره (MTProto + Vless) با سیستم کَش هوشمند فعال شد.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()