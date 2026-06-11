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
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import io

# ─── تنظیمات ───────────────────────────────────────────
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
SEND_INTERVAL_MINUTES = 5

PROXY_SOURCES = {
    'proxybolt': 'https://proxybolt.link/',
    'text_files': [
        f"https://raw.githubusercontent.com/V2RAYCONFIGSPOOL/TELEGRAM_PROXY_SUB/refs/heads/main/telegram_proxy_no{i}.txt"
        for i in range(1, 21)
    ]
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

COUNTRY_FLAGS = {
    "United States": "🇺🇸", "Germany": "🇩🇪", "Netherlands": "🇳🇱",
    "France": "🇫🇷", "United Kingdom": "🇬🇧", "Canada": "🇨🇦",
    "Singapore": "🇸🇬", "Japan": "🇯🇵", "Russia": "🇷🇺",
    "Ukraine": "🇺🇦", "Finland": "🇫🇮", "Sweden": "🇸🇪",
    "Poland": "🇵🇱", "Turkey": "🇹🇷", "Iran": "🇮🇷",
    "China": "🇨🇳", "South Korea": "🇰🇷", "Brazil": "🇧🇷",
    "India": "🇮🇳", "Australia": "🇦🇺", "Switzerland": "🇨🇭",
    "Austria": "🇦🇹", "Czech Republic": "🇨🇿", "Romania": "🇷🇴",
    "Hungary": "🇭🇺", "Bulgaria": "🇧🇬", "Latvia": "🇱🇻",
    "Lithuania": "🇱🇹", "Estonia": "🇪🇪", "Moldova": "🇲🇩",
    "Luxembourg": "🇱🇺", "Belgium": "🇧🇪", "Italy": "🇮🇹",
    "Spain": "🇪🇸", "Portugal": "🇵🇹", "Norway": "🇳🇴",
    "Denmark": "🇩🇰", "Israel": "🇮🇱", "UAE": "🇦🇪",
    "Saudi Arabia": "🇸🇦", "Mexico": "🇲🇽",
}

_geo_cache    = {}
_last_proxies = []
_stats = {
    "total_checked": 0,
    "total_active":  0,
    "best_ping":     9999,
    "best_country":  "",
    "send_count":    0,
    "start_time":    datetime.now(),
}


# ══════════════════════════════════════════════════════════
#  ابزارها
# ══════════════════════════════════════════════════════════

def get_location(host):
    if not host:
        return {"country": "Unknown", "city": "", "isp": "", "flag": "🌍"}
    if host in _geo_cache:
        return _geo_cache[host]
    try:
        r = requests.get(f"http://ip-api.com/json/{host}?fields=country,city,isp", timeout=5)
        d = r.json()
        if d.get('country'):
            country = d['country']
            result = {
                "country": country,
                "city":    d.get('city', ''),
                "isp":     d.get('isp', ''),
                "flag":    COUNTRY_FLAGS.get(country, '🌍')
            }
            _geo_cache[host] = result
            return result
    except Exception:
        pass
    result = {"country": "Unknown", "city": "", "isp": "", "flag": "🌍"}
    _geo_cache[host] = result
    return result


def ping_label(ms, from_iran=False):
    flag = "🇮🇷 " if from_iran else ""
    if ms is None:
        return "❌ N/A"
    elif ms < 80:
        return f"{flag}🟢 {ms}ms"
    elif ms < 200:
        return f"{flag}🟡 {ms}ms"
    else:
        return f"{flag}🔴 {ms}ms"


def parse_proxy_link(line):
    line = line.strip()
    if not line:
        return None
    if "t.me/proxy" in line:
        tg_link = line.replace("https://t.me/proxy", "tg://proxy", 1)
        tg_link = tg_link.replace("http://t.me/proxy", "tg://proxy", 1)
    elif line.startswith("tg://proxy"):
        tg_link = line
    else:
        return None
    try:
        parsed = urlparse(tg_link)
        params = parse_qs(parsed.query)
        host   = params.get('server', [''])[0]
        port   = params.get('port', [''])[0]
        secret = params.get('secret', [''])[0]
        if not host or not port:
            return None
        return {"link": tg_link, "host": host, "port": port, "secret": secret,
                "name": "", "country": "", "city": "", "isp": "", "flag": "🌍", "ping": None}
    except Exception:
        return None


def escape_md(text):
    text = str(text)
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f'\\{ch}')
    return text


# ══════════════════════════════════════════════════════════
#  دریافت پروکسی
# ══════════════════════════════════════════════════════════

def get_from_proxybolt():
    try:
        r = requests.get(PROXY_SOURCES['proxybolt'], headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, 'html.parser')
        app_div = soup.find('div', id='app')
        if not app_div or 'data-page' not in app_div.attrs:
            return []
        page_data   = json.loads(app_div['data-page'])
        proxies_raw = page_data.get('props', {}).get('proxies', [])
        print(f"✅ ProxyBolt: {len(proxies_raw)} پروکسی")
        result = []
        for p in proxies_raw:
            if p.get('host'):
                link = f"tg://proxy?server={p['host']}&port={p['port']}&secret={p.get('secret','')}"
                result.append({"link": link, "host": p['host'], "port": str(p['port']),
                                "secret": p.get('secret', ''), "name": p.get('name', ''),
                                "country": "", "city": "", "isp": "", "flag": "🌍", "ping": None})
        return result
    except Exception as e:
        print(f"❌ ProxyBolt: {e}")
        return []


def get_from_text_files():
    all_proxies = []
    for url in PROXY_SOURCES['text_files']:
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            r.raise_for_status()
            for line in r.text.strip().split('\n'):
                proxy = parse_proxy_link(line)
                if proxy:
                    all_proxies.append(proxy)
        except Exception:
            continue
    print(f"✅ فایل‌های متنی: {len(all_proxies)} پروکسی")
    return all_proxies


# نودهای ایران در check-host.net
IRAN_NODES = [
    "ir1.node.check-host.net",  # تهران
    "ir4.node.check-host.net",  # تبریز
    "ir3.node.check-host.net",  # شیراز
    "ir6.node.check-host.net",  # کرج
]

_checkhost_headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

def get_iran_ping(host, port):
    """پینگ از ایران با check-host.net API"""
    try:
        nodes = random.sample(IRAN_NODES, 2)
        node_params = "&".join([f"node={n}" for n in nodes])
        url = f"https://check-host.net/check-tcp?host={host}:{port}&max_nodes=2&{node_params}"
        r = requests.get(url, headers=_checkhost_headers, timeout=10)
        request_id = r.json().get("request_id")
        if not request_id:
            return None

        time.sleep(3)  # صبر برای انجام چک

        result = requests.get(
            f"https://check-host.net/check-result/{request_id}",
            headers=_checkhost_headers, timeout=10
        ).json()

        pings = []
        for node_result in result.values():
            if not node_result:
                continue
            if isinstance(node_result, list):
                for item in node_result:
                    if isinstance(item, dict) and "time" in item:
                        pings.append(int(item["time"] * 1000))
                    elif isinstance(item, list) and item:
                        for sub in item:
                            if isinstance(sub, (int, float)):
                                pings.append(int(sub * 1000))
                                break

        return min(pings) if pings else None
    except Exception:
        return None


def check_and_ping(proxy):
    """چک اتصال + پینگ از ایران"""
    try:
        host, port = proxy['host'], int(proxy['port'])

        # چک سریع اتصال
        start = time.time()
        with socket.create_connection((host, port), timeout=3):
            local_ping = int((time.time() - start) * 1000)

        # پینگ از ایران
        iran_ping = get_iran_ping(host, port)
        proxy['ping'] = iran_ping if iran_ping is not None else local_ping
        proxy['from_iran'] = iran_ping is not None
        return proxy
    except Exception:
        return None


def get_active_proxies(max_check=100, return_count=5, country_filter=None):
    global _stats, _last_proxies

    all_p = get_from_proxybolt() + get_from_text_files()

    seen, unique = set(), []
    for p in all_p:
        key = f"{p['host']}:{p['port']}"
        if key not in seen:
            seen.add(key)
            unique.append(p)

    print(f"📊 کل: {len(unique)}")
    _stats["total_checked"] += min(len(unique), max_check)

    with ThreadPoolExecutor(max_workers=40) as ex:
        results = list(ex.map(check_and_ping, unique[:max_check]))
    active = [r for r in results if r is not None]
    active.sort(key=lambda x: x.get('ping') or 9999)

    print(f"✅ فعال: {len(active)}")
    _stats["total_active"] += len(active)

    if active and active[0].get('ping', 9999) < _stats["best_ping"]:
        _stats["best_ping"] = active[0]['ping']

    # اضافه کردن لوکیشن و فیلتر
    final = []
    for p in active:
        if len(final) >= return_count:
            break
        geo = get_location(p['host'])
        p.update(geo)
        time.sleep(0.1)
        if country_filter:
            if country_filter.lower() not in geo['country'].lower():
                continue
        final.append(p)

    if final:
        _stats["best_country"] = final[0].get('flag', '') + ' ' + final[0].get('country', '')

    _last_proxies = final
    return final


# ══════════════════════════════════════════════════════════
#  بنر گرافیکی
# ══════════════════════════════════════════════════════════

def create_banner(proxies):
    W = 800
    H = 90 + len(proxies) * 95 + 40
    img  = Image.new('RGB', (W, H), color=(15, 15, 28))
    draw = ImageDraw.Draw(img)

    # هدر
    draw.rectangle([0, 0, W, 65], fill=(25, 25, 55))
    draw.text((W // 2, 22), "🔐  Telegram Proxy List", fill=(130, 180, 255), anchor="mm")
    draw.text((W // 2, 50), datetime.now().strftime("%Y-%m-%d   %H:%M  UTC"), fill=(100, 100, 160), anchor="mm")
    draw.line([(0, 66), (W, 66)], fill=(50, 50, 100), width=2)

    y = 76
    for i, p in enumerate(proxies):
        ping      = p.get('ping')
        from_iran = p.get('from_iran', False)
        flag      = p.get('flag', '🌍')
        country   = p.get('country', 'Unknown')
        city      = p.get('city', '')
        host      = p.get('host', '')
        port      = p.get('port', '')

        if ping is None:
            pc, pt = (180, 60, 60),  "N/A"
        elif ping < 80:
            pc, pt = (60, 210, 100), f"{ping} ms"
        elif ping < 200:
            pc, pt = (210, 190, 60), f"{ping} ms"
        else:
            pc, pt = (210, 100, 60), f"{ping} ms"

        iran_label = " 🇮🇷" if from_iran else ""

        draw.rounded_rectangle([12, y, W - 12, y + 82], radius=12, fill=(22, 22, 42))
        draw.text((36, y + 14), f"#{i+1}", fill=(80, 130, 240))

        loc = f"{flag}  {city + ', ' if city else ''}{country}"
        draw.text((68, y + 11), loc, fill=(220, 220, 255))
        draw.text((68, y + 40), f"  {host}:{port}", fill=(140, 200, 150))

        # ping badge
        draw.rounded_rectangle([W - 145, y + 20, W - 25, y + 60], radius=8, fill=(30, 30, 55))
        draw.text(((W - 145 + W - 25) // 2, y + 33), pt + iran_label, fill=pc, anchor="mm")
        if from_iran:
            draw.text(((W - 145 + W - 25) // 2, y + 52), "از ایران", fill=(150, 150, 200), anchor="mm")

        y += 92

    # فوتر
    draw.rectangle([0, H - 35, W, H], fill=(20, 20, 45))
    draw.text((W // 2, H - 17),
              f"Auto update every {SEND_INTERVAL_MINUTES} min  •  Sorted by speed",
              fill=(80, 80, 130), anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


# ══════════════════════════════════════════════════════════
#  ارسال پست
# ══════════════════════════════════════════════════════════

def format_caption(proxies):
    lines = ["🔐 *پروکسی‌های تلگرام \\- فعال و تست شده*", "━━━━━━━━━━━━━━━━━━━━\n"]
    for i, p in enumerate(proxies, 1):
        flag       = p.get('flag', '🌍')
        country    = escape_md(p.get('country', 'Unknown'))
        city       = escape_md(p.get('city', ''))
        isp        = escape_md(p.get('isp', ''))
        host       = p.get('host', '')
        port       = p.get('port', '')
        link       = p.get('link', '')
        from_iran  = p.get('from_iran', False)
        loc        = f"{city}, {country}" if city else country
        lines.append(f"*{i}\\. {flag} {loc}*")
        lines.append(f"⚡ {escape_md(ping_label(p.get('ping'), from_iran))}")
        lines.append(f"🖥 `{host}:{port}`")
        if isp:
            lines.append(f"🏢 {isp}")
        lines.append(f"[🔗 اتصال مستقیم]({link})\n")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"⏱ بروزرسانی هر {SEND_INTERVAL_MINUTES} دقیقه")
    lines.append("✅ مرتب‌شده بر اساس سرعت")
    return "\n".join(lines)


async def send_proxy_post(bot, proxies=None, country_filter=None, chat_id=None):
    global _stats
    target = chat_id or CHANNEL_ID
    if proxies is None:
        proxies = get_active_proxies(max_check=100, return_count=5, country_filter=country_filter)
    if not proxies:
        return
    caption = format_caption(proxies)
    try:
        banner = create_banner(proxies)
        await bot.send_photo(chat_id=target, photo=banner, caption=caption, parse_mode="MarkdownV2")
    except Exception:
        await bot.send_message(chat_id=target, text=caption, parse_mode="MarkdownV2",
                               disable_web_page_preview=True)
    _stats["send_count"] += 1
    print(f"✅ پست #{_stats['send_count']} ارسال شد")


# ══════════════════════════════════════════════════════════
#  نوتیف قطعی
# ══════════════════════════════════════════════════════════

async def check_alive_and_notify(bot):
    global _last_proxies
    if not _last_proxies:
        return
    dead = [p for p in _last_proxies if check_and_ping(dict(p)) is None]
    if dead:
        lines = ["⚠️ *هشدار: پروکسی‌های زیر قطع شدند\\!*\n"]
        for p in dead:
            lines.append(f"❌ `{p['host']}:{p['port']}` {p.get('flag','')} {escape_md(p.get('country',''))}")
        lines.append("\n🔄 پروکسی جدید در حال ارسال\\.\\.\\.")
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text="\n".join(lines), parse_mode="MarkdownV2")
        except Exception as e:
            print(f"❌ نوتیف: {e}")


# ══════════════════════════════════════════════════════════
#  آمار روزانه
# ══════════════════════════════════════════════════════════

async def send_daily_stats(bot):
    uptime = datetime.now() - _stats["start_time"]
    h = int(uptime.total_seconds() // 3600)
    lines = [
        "📊 *آمار روزانه کانال*",
        "━━━━━━━━━━━━━━━\n",
        f"🔍 کل پروکسی چک‌شده: `{_stats['total_checked']}`",
        f"✅ کل پروکسی فعال: `{_stats['total_active']}`",
        f"📤 تعداد پست‌ها: `{_stats['send_count']}`",
        f"🏆 بهترین ping: `{_stats['best_ping']}ms` {escape_md(_stats['best_country'])}",
        f"⏳ آپتایم: `{h}` ساعت",
        "\n━━━━━━━━━━━━━━━",
        "💡 به ربات پیام بده و پروکسی بگیر\\!"
    ]
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text="\n".join(lines), parse_mode="MarkdownV2")
    except Exception as e:
        print(f"❌ آمار: {e}")


# ══════════════════════════════════════════════════════════
#  کامندهای ربات
# ══════════════════════════════════════════════════════════

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 ۵ پروکسی تصادفی",         callback_data="get_5")],
        [InlineKeyboardButton("⚡ سریع‌ترین‌ها (زیر ۵۰ms)", callback_data="get_fast")],
        [
            InlineKeyboardButton("🇩🇪 آلمان",  callback_data="country_Germany"),
            InlineKeyboardButton("🇳🇱 هلند",   callback_data="country_Netherlands"),
            InlineKeyboardButton("🇺🇸 آمریکا", callback_data="country_United States"),
        ],
        [
            InlineKeyboardButton("🇫🇮 فنلاند", callback_data="country_Finland"),
            InlineKeyboardButton("🇫🇷 فرانسه", callback_data="country_France"),
            InlineKeyboardButton("🇸🇪 سوئد",   callback_data="country_Sweden"),
        ],
        [InlineKeyboardButton("📊 آمار ربات", callback_data="stats")],
    ])


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *سلام\\! به ربات پروکسی خوش اومدی* 🎉\n\n"
        "از دکمه‌های زیر پروکسی دلخواهت رو انتخاب کن:\n\n"
        f"🔄 کانال هر `{SEND_INTERVAL_MINUTES}` دقیقه آپدیت میشه\n"
        "⚡ پروکسی‌ها بر اساس سرعت مرتب‌ان\n"
        "🌍 لوکیشن و ISP هر پروکسی نشون داده میشه"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=main_keyboard())


async def cmd_proxy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ در حال دریافت پروکسی\\.\\.\\.", parse_mode="MarkdownV2")
    proxies = get_active_proxies(return_count=5)
    await msg.delete()
    await send_proxy_post(ctx.bot, proxies=proxies, chat_id=update.effective_chat.id)


async def cmd_fast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⚡ جستجوی سریع‌ترین پروکسی‌ها\\.\\.\\.", parse_mode="MarkdownV2")
    proxies = get_active_proxies(max_check=120, return_count=10)
    fast = [p for p in proxies if p.get('ping') and p['ping'] < 50][:5] or proxies[:5]
    await msg.delete()
    await send_proxy_post(ctx.bot, proxies=fast, chat_id=update.effective_chat.id)


async def cmd_country(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "📌 مثال: `/country germany`\n`/country netherlands`\n`/country finland`",
            parse_mode="MarkdownV2"
        )
        return
    country = " ".join(ctx.args)
    msg = await update.message.reply_text(
        f"🌍 جستجوی پروکسی {escape_md(country)}\\.\\.\\.", parse_mode="MarkdownV2"
    )
    proxies = get_active_proxies(max_check=120, return_count=5, country_filter=country)
    await msg.delete()
    if proxies:
        await send_proxy_post(ctx.bot, proxies=proxies, chat_id=update.effective_chat.id)
    else:
        await update.message.reply_text(
            f"❌ پروکسی از {escape_md(country)} پیدا نشد\\.", parse_mode="MarkdownV2"
        )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    h = int((datetime.now() - _stats["start_time"]).total_seconds() // 3600)
    text = (
        "📊 *آمار ربات*\n━━━━━━━━━━━━━━━\n\n"
        f"🔍 کل چک‌شده: `{_stats['total_checked']}`\n"
        f"✅ کل فعال: `{_stats['total_active']}`\n"
        f"📤 پست‌های ارسالی: `{_stats['send_count']}`\n"
        f"🏆 بهترین ping: `{_stats['best_ping']}ms`\n"
        f"⏳ آپتایم: `{h}` ساعت"
    )
    # هم از پیام مستقیم هم از دکمه کار می‌کنه
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="MarkdownV2")
    elif update.message:
        await update.message.reply_text(text, parse_mode="MarkdownV2")


async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data
    cid   = query.message.chat_id

    loading = await query.message.reply_text("⏳ لطفاً صبر کن\\.\\.\\.", parse_mode="MarkdownV2")

    if data == "get_5":
        proxies = get_active_proxies(return_count=5)
    elif data == "get_fast":
        all_p   = get_active_proxies(max_check=120, return_count=10)
        proxies = [p for p in all_p if p.get('ping') and p['ping'] < 50][:5] or all_p[:5]
    elif data.startswith("country_"):
        country = data.replace("country_", "")
        proxies = get_active_proxies(max_check=120, return_count=5, country_filter=country)
    elif data == "stats":
        await loading.delete()
        await cmd_stats(update, ctx)
        return
    else:
        proxies = []

    await loading.delete()

    if proxies:
        await send_proxy_post(ctx.bot, proxies=proxies, chat_id=cid)
    else:
        await query.message.reply_text("❌ پروکسی پیدا نشد\\. دوباره امتحان کن\\.", parse_mode="MarkdownV2")


# ══════════════════════════════════════════════════════════
#  زمان‌بند
# ══════════════════════════════════════════════════════════

def run_schedule(bot_instance):
    def sync_periodic():
        async def _job():
            await check_alive_and_notify(bot_instance)
            await send_proxy_post(bot_instance)
        asyncio.run(_job())

    def sync_daily():
        asyncio.run(send_daily_stats(bot_instance))

    schedule.every(SEND_INTERVAL_MINUTES).minutes.do(sync_periodic)
    schedule.every().day.at("09:00").do(sync_daily)

    print(f"⏰ زمان‌بند فعال: هر {SEND_INTERVAL_MINUTES} دقیقه")
    while True:
        schedule.run_pending()
        time.sleep(15)


# ══════════════════════════════════════════════════════════
#  main
# ══════════════════════════════════════════════════════════

def main():
    print("🚀 ربات پروکسی شروع به کار کرد!")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("proxy",   cmd_proxy))
    app.add_handler(CommandHandler("fast",    cmd_fast))
    app.add_handler(CommandHandler("country", cmd_country))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # زمان‌بند در thread جداگانه
    bot_instance = Bot(token=BOT_TOKEN)
    threading.Thread(target=run_schedule, args=(bot_instance,), daemon=True).start()

    # پست اول
    asyncio.get_event_loop().run_until_complete(send_proxy_post(bot_instance))

    print("🤖 ربات در حال اجراست...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
