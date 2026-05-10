"""
FileLink Bot — Instant Edition
Stores only the file_id (a Telegram pointer). Zero bytes transferred.
Links work by re-sending via file_id, which is instant regardless of file size.
"""
import os, hashlib, time, logging
from collections import defaultdict

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

import database as db
import config

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Rate limiter ─────────────────────────────────────────────────────────────
_rate: dict[int, list] = defaultdict(list)
def throttled(uid):
    now = time.time()
    calls = [t for t in _rate[uid] if now - t < 60]
    _rate[uid] = calls
    if len(calls) >= config.RATE_LIMIT: return True
    _rate[uid].append(now); return False

def sid(): return hashlib.md5(str(time.time_ns()).encode()).hexdigest()[:8]
def fmt(n):
    for u in ("B","KB","MB","GB"):
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def kb(short_id):
    link = f"https://t.me/{config.BOT_USERNAME}?start=file_{short_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Share", url=f"https://t.me/share/url?url={link}")],
        [InlineKeyboardButton("📋 Info", callback_data=f"info:{short_id}"),
         InlineKeyboardButton("🗑 Delete", callback_data=f"del:{short_id}")],
        [InlineKeyboardButton("📂 My Files", callback_data="myfiles:0")],
    ])

# ── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_user(user.id, user.username or "", user.full_name)

    if ctx.args and ctx.args[0].startswith("file_"):
        rec = db.get_file(ctx.args[0][5:])
        if rec:
            # Re-send via file_id — instant, no size limit
            await ctx.bot.send_document(
                chat_id=update.effective_chat.id,
                document=rec["file_id"],
                caption=f"📄 *{rec['file_name']}*  •  `{fmt(rec['file_size'])}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text("❌ File not found.")
        return

    await update.message.reply_text(
        f"👋 *Hey {user.first_name}!*\n\n"
        "Send me any file → get an instant shareable link.\n"
        "No size limit\\. No upload\\. Just a link\\.\n\n"
        "/myfiles /stats /search /help",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Files", callback_data="myfiles:0"),
             InlineKeyboardButton("📊 Stats", callback_data="stats")],
        ]),
    )

# ── Core: handle any file ─────────────────────────────────────────────────────
ANY_FILE = (
    filters.Document.ALL | filters.PHOTO | filters.VIDEO |
    filters.AUDIO | filters.VOICE | filters.VIDEO_NOTE | filters.Sticker.ALL
)

async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_user(user.id, user.username or "", user.full_name)
    if throttled(user.id):
        await update.message.reply_text(f"⏳ Max {config.RATE_LIMIT}/min — slow down.")
        return

    msg = update.message
    media = (msg.document or (msg.photo[-1] if msg.photo else None) or
             msg.video or msg.audio or msg.voice or msg.video_note or msg.sticker)
    if not media: return

    short = sid()
    file_name = getattr(media, "file_name", None) or f"file_{short}"
    file_size = getattr(media, "file_size", 0) or 0
    mime      = getattr(media, "mime_type", None)
    file_id   = media.file_id   # ← just a string, no bytes moved

    db.save_file(
        short_id=short, user_id=user.id, file_id=file_id,
        file_name=file_name, file_size=file_size, mime_type=mime, msg_id=msg.message_id,
    )

    link = f"https://t.me/{config.BOT_USERNAME}?start=file_{short}"
    await msg.reply_text(
        f"✅ *Done\\!*\n\n"
        f"📄 `{file_name}`\n"
        f"📦 `{fmt(file_size)}`\n\n"
        f"🔗 *Link:*\n`{link}`",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb(short),
        disable_web_page_preview=True,
    )

# ── /myfiles (paginated) ──────────────────────────────────────────────────────
PAGE = 5
async def myfiles(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    page = int(ctx.args[0]) if ctx.args else 0
    await _filelist(update, ctx, update.effective_user.id, page)

async def _filelist(update, ctx, uid, page):
    files = db.get_user_files(uid, limit=PAGE, offset=page * PAGE)
    total = db.count_user_files(uid)
    pages = max(1, -(-total // PAGE))
    if not files:
        text = "📂 No files yet — send me something\\!"
    else:
        lines = [f"📂 *Your Files* \\(page {page+1}/{pages}\\)\n"]
        for f in files:
            link = f"https://t.me/{config.BOT_USERNAME}?start=file_{f['short_id']}"
            name = f['file_name'].replace('_','\_').replace('.','\.').replace('-','\-').replace('(', '\(').replace(')', '\)')
            lines.append(f"• [{name}]({link}) · `{f['short_id']}` · {fmt(f['file_size'])}")
        text = "\n".join(lines)

    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"myfiles:{page-1}"))
    if (page+1)*PAGE < total: nav.append(InlineKeyboardButton("➡️", callback_data=f"myfiles:{page+1}"))
    rows = ([nav] if nav else []) + [[InlineKeyboardButton("📊 Stats", callback_data="stats")]]
    kb2 = InlineKeyboardMarkup(rows)

    msg = update.message or update.callback_query.message
    fn = msg.edit_text if update.callback_query else msg.reply_text
    await fn(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb2, disable_web_page_preview=True)

# ── /stats ────────────────────────────────────────────────────────────────────
async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = db.get_user_stats(update.effective_user.id)
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        f"📊 *Stats*\n\n"
        f"📁 Files: *{s['count']}*\n"
        f"💾 Total: *{fmt(s['total_size'])}*\n"
        f"🕐 Last: `{s['last_upload'] or 'never'}`",
        parse_mode=ParseMode.MARKDOWN,
    )

# ── /search ───────────────────────────────────────────────────────────────────
async def search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/search <name>`", parse_mode=ParseMode.MARKDOWN); return
    q = " ".join(ctx.args)
    results = db.search_files(update.effective_user.id, q)
    if not results:
        await update.message.reply_text(f"🔍 Nothing found for *{q}*.", parse_mode=ParseMode.MARKDOWN); return
    lines = [f"🔍 *Results for* `{q}`\n"]
    for f in results[:10]:
        link = f"https://t.me/{config.BOT_USERNAME}?start=file_{f['short_id']}"
        lines.append(f"• [{f['file_name']}]({link}) · `{f['short_id']}`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

# ── /delete ───────────────────────────────────────────────────────────────────
async def delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/delete <id>`", parse_mode=ParseMode.MARKDOWN); return
    rec = db.get_file(ctx.args[0])
    if not rec: await update.message.reply_text("❌ Not found."); return
    if rec["user_id"] != update.effective_user.id: await update.message.reply_text("⛔ Not yours."); return
    db.delete_file(ctx.args[0])
    await update.message.reply_text(f"✅ Deleted `{ctx.args[0]}`.", parse_mode=ParseMode.MARKDOWN)

# ── /help ─────────────────────────────────────────────────────────────────────
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help*\n\n"
        "Send any file → instant link\\.\n\n"
        "/myfiles — browse uploads\n"
        "/stats   — usage stats\n"
        "/search  — find by name\n"
        "/delete  — delete by ID\n"
        "/help    — this message",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

# ── Callbacks ─────────────────────────────────────────────────────────────────
async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data; uid = q.from_user.id
    if data.startswith("myfiles:"): await _filelist(update, ctx, uid, int(data.split(":")[1]))
    elif data == "stats": await stats(update, ctx)
    elif data.startswith("info:"):
        rec = db.get_file(data.split(":")[1])
        if rec:
            link = f"https://t.me/{config.BOT_USERNAME}?start=file_{rec['short_id']}"
            await q.message.reply_text(
                f"📋 *Info*\n\n🆔 `{rec['short_id']}`\n📄 `{rec['file_name']}`\n"
                f"📦 `{fmt(rec['file_size'])}`\n🗂 `{rec['mime_type'] or 'unknown'}`\n"
                f"📅 `{rec['created_at']}`\n\n🔗 `{link}`",
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
            )
    elif data.startswith("del:"):
        sid_val = data.split(":")[1]; rec = db.get_file(sid_val)
        if rec and rec["user_id"] == uid:
            db.delete_file(sid_val); await q.message.edit_text("🗑 Deleted.")
        else: await q.answer("Not found or not yours.", show_alert=True)

# ── Boot ──────────────────────────────────────────────────────────────────────
async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start",   "Welcome / retrieve a file"),
        BotCommand("myfiles", "Browse your files"),
        BotCommand("stats",   "Usage stats"),
        BotCommand("search",  "Search by filename"),
        BotCommand("delete",  "Delete a file"),
        BotCommand("help",    "Command reference"),
    ], scope=BotCommandScopeDefault())

def main():
    application = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()
    for cmd, fn in [("start",start),("myfiles",myfiles),("stats",stats),
                    ("search",search),("delete",delete),("help",help_cmd)]:
        application.add_handler(CommandHandler(cmd, fn))
    application.add_handler(CallbackQueryHandler(on_cb))
    application.add_handler(MessageHandler(ANY_FILE, handle_file))
    log.info("Bot running — instant file_id mode")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
