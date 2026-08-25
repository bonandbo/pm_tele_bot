"""
Bot Telegram cho VLTK Dev Tracker.

Lệnh chính:
  /bug          — báo cáo bug mới (hội thoại từng bước)
  /feature      — đề xuất feature mới
  /bugs         — xem danh sách bug (lọc theo version / status)
  /features     — xem danh sách feature
  /status BUG-1 — đổi trạng thái 1 bug/feature (chỉ admin)
  /me           — xem các bug/feature mình đã report
  /huy          — huỷ thao tác đang làm dở
"""
import html
import logging
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
import notion_client as nc

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

# Trạng thái hội thoại
(
    BUG_TITLE, BUG_DESC, BUG_STEPS, BUG_SEVERITY,
    BUG_VERSION, BUG_MODULE, BUG_IMAGE,
) = range(7)
(
    FEAT_TITLE, FEAT_DESC, FEAT_IMPACT, FEAT_EFFORT, FEAT_IMAGE,
) = range(100, 105)

SKIP = "Bỏ qua"


# ------------------------------------------------------------------ tiện ích

def _kb(options: list[str], cols: int = 2, add_skip: bool = False) -> ReplyKeyboardMarkup:
    rows = [options[i:i + cols] for i in range(0, len(options), cols)]
    if add_skip:
        rows.append([SKIP])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def _is_admin(update: Update) -> bool:
    if not config.ADMIN_USER_IDS:
        return True
    return update.effective_user.id in config.ADMIN_USER_IDS


def _reporter_name(update: Update) -> str:
    u = update.effective_user
    return f"@{u.username}" if u.username else (u.full_name or str(u.id))


async def _file_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Lấy URL tạm của ảnh Telegram. Xem README về giới hạn thời hạn link."""
    msg = update.message
    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file_id = msg.document.file_id
    if not file_id:
        return None
    f = await context.bot.get_file(file_id)
    return f.file_path


# ------------------------------------------------------------------ /start

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>VLTK Dev Tracker Bot</b>\n\n"
        "🐛 /bug — báo cáo bug mới\n"
        "💡 /feature — đề xuất tính năng\n"
        "📋 /bugs — xem danh sách bug\n"
        "📋 /features — xem danh sách feature\n"
        "🔄 /status &lt;ID&gt; — đổi trạng thái (admin)\n"
        "👤 /me — xem những gì mình đã gửi\n"
        "❌ /huy — huỷ thao tác đang làm\n\n"
        "Mọi thứ được lưu thẳng vào Notion, bấm nút để mở trang chi tiết.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Đã huỷ.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ------------------------------------------------------------------ /bug

async def bug_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "🐛 <b>Báo cáo bug mới</b>\n\nTiêu đề ngắn gọn của bug là gì?\n"
        "<i>(gõ /huy để dừng)</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
    return BUG_TITLE


async def bug_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text("Mô tả chi tiết bug (hiện tượng, ảnh hưởng gì)?")
    return BUG_DESC


async def bug_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["desc"] = update.message.text.strip()
    await update.message.reply_text(
        "Các bước tái hiện bug? Ghi từng bước một dòng.",
        reply_markup=_kb([], add_skip=True),
    )
    return BUG_STEPS


async def bug_steps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["steps"] = "" if text == SKIP else text
    await update.message.reply_text(
        "Mức độ nghiêm trọng?", reply_markup=_kb(config.SEVERITIES)
    )
    return BUG_SEVERITY


async def bug_severity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    context.user_data["severity"] = val if val in config.SEVERITIES else None
    versions = _known_versions()
    await update.message.reply_text(
        "Phát hiện ở version nào?", reply_markup=_kb(versions, add_skip=True)
    )
    return BUG_VERSION


def _known_versions() -> list[str]:
    """Danh sách version — sửa ở đây khi có build mới, hoặc thêm option trong Notion."""
    return ["v1.0", "v1.1", "v1.2"]


async def bug_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    context.user_data["version"] = None if val == SKIP else val
    await update.message.reply_text(
        "Bug thuộc module nào?", reply_markup=_kb(config.MODULES, cols=2, add_skip=True)
    )
    return BUG_MODULE


async def bug_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    context.user_data["modules"] = [] if val == SKIP else [val]
    await update.message.reply_text(
        "Gửi ảnh/screenshot nếu có. Không có thì bấm Bỏ qua.",
        reply_markup=_kb([], add_skip=True),
    )
    return BUG_IMAGE


async def bug_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    urls = []
    if update.message.photo or update.message.document:
        url = await _file_url(update, context)
        if url:
            urls.append(url)

    d = context.user_data
    await update.message.reply_text("Đang lưu vào Notion...", reply_markup=ReplyKeyboardRemove())

    try:
        page = await nc.create_bug(
            title=d["title"],
            description=d.get("desc", ""),
            steps=d.get("steps", ""),
            severity=d.get("severity"),
            version_found=d.get("version"),
            modules=d.get("modules"),
            reporter=_reporter_name(update),
            telegram_id=str(update.effective_chat.id),
            image_urls=urls,
        )
    except Exception as exc:
        log.exception("Tạo bug thất bại")
        await update.message.reply_text(f"❌ Lỗi khi lưu vào Notion: {exc}")
        context.user_data.clear()
        return ConversationHandler.END

    url = nc.page_url(page["id"])
    short_id = nc.get_short_id(page, config.BUG_PROPS["id"])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📄 Mở trong Notion", url=url)]])
    await update.message.reply_text(
        f"✅ Đã ghi nhận <b>{short_id}</b>\n{html.escape(d['title'])}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )

    if config.ADMIN_CHAT_ID and str(update.effective_chat.id) != config.ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                config.ADMIN_CHAT_ID,
                f"🐛 Bug mới <b>{short_id}</b> từ {html.escape(_reporter_name(update))}\n"
                f"{html.escape(d['title'])}",
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        except Exception:
            log.warning("Không gửi được thông báo tới admin chat")

    context.user_data.clear()
    return ConversationHandler.END


# ------------------------------------------------------------------ /feature

async def feat_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "💡 <b>Đề xuất tính năng</b>\n\nTên feature là gì?\n<i>(gõ /huy để dừng)</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
    return FEAT_TITLE


async def feat_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text("Mô tả feature và lý do cần có nó?")
    return FEAT_DESC


async def feat_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["desc"] = update.message.text.strip()
    await update.message.reply_text(
        "Mức độ ảnh hưởng tới trải nghiệm người chơi?",
        reply_markup=_kb(config.IMPACTS, cols=3),
    )
    return FEAT_IMPACT


async def feat_impact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    context.user_data["impact"] = val if val in config.IMPACTS else None
    await update.message.reply_text(
        "Ước lượng công sức làm?", reply_markup=_kb(config.EFFORTS, cols=3, add_skip=True)
    )
    return FEAT_EFFORT


async def feat_effort(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    context.user_data["effort"] = None if val == SKIP else val
    await update.message.reply_text(
        "Có ảnh tham khảo (mockup, game khác) không? Không thì bấm Bỏ qua.",
        reply_markup=_kb([], add_skip=True),
    )
    return FEAT_IMAGE


async def feat_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    urls = []
    if update.message.photo or update.message.document:
        url = await _file_url(update, context)
        if url:
            urls.append(url)

    d = context.user_data
    await update.message.reply_text("Đang lưu vào Notion...", reply_markup=ReplyKeyboardRemove())

    try:
        page = await nc.create_feature(
            title=d["title"],
            description=d.get("desc", ""),
            impact=d.get("impact"),
            effort=d.get("effort"),
            reporter=_reporter_name(update),
            telegram_id=str(update.effective_chat.id),
            image_urls=urls,
        )
    except Exception as exc:
        log.exception("Tạo feature thất bại")
        await update.message.reply_text(f"❌ Lỗi khi lưu vào Notion: {exc}")
        context.user_data.clear()
        return ConversationHandler.END

    url = nc.page_url(page["id"])
    short_id = nc.get_short_id(page, config.FEATURE_PROPS["id"])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📄 Mở trong Notion", url=url)]])
    await update.message.reply_text(
        f"✅ Đã ghi nhận <b>{short_id}</b>\n{html.escape(d['title'])}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    context.user_data.clear()
    return ConversationHandler.END


# ------------------------------------------------------------------ /bugs

async def cmd_bugs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = [a.strip() for a in context.args] if context.args else []
    version = next((a for a in args if a.lower().startswith("v")), None)
    open_only = any(a.lower() in ("open", "mở", "chua", "chưa") for a in args)
    status = next((s for s in config.BUG_STATUSES if s.lower() in " ".join(args).lower()), None)

    if not args:
        open_only = True

    await update.message.chat.send_action("typing")
    try:
        pages = await nc.query_bugs(version=version, status=status, open_only=open_only)
    except Exception as exc:
        await update.message.reply_text(f"❌ Không lấy được dữ liệu: {exc}")
        return

    if not pages:
        await update.message.reply_text("Không có bug nào khớp điều kiện. 🎉")
        return

    header = "🐛 <b>Danh sách bug</b>"
    if version:
        header += f" — {version}"
    if status:
        header += f" — {status}"
    elif open_only:
        header += " — chưa xử lý xong"

    lines = [header, ""]
    buttons = []
    for page in pages[:20]:
        lines.append(nc.format_bug_line(page))
        short_id = nc.get_short_id(page, config.BUG_PROPS["id"])
        title = nc.get_title(page, config.BUG_PROPS["title"])
        label = f"{short_id} · {title[:28]}"
        buttons.append([InlineKeyboardButton(label, url=nc.page_url(page["id"]))])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


async def cmd_features(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = [a.strip() for a in context.args] if context.args else []
    version = next((a for a in args if a.lower().startswith("v")), None)
    status = next((s for s in config.FEATURE_STATUSES if s.lower() in " ".join(args).lower()), None)

    await update.message.chat.send_action("typing")
    try:
        pages = await nc.query_features(version=version, status=status)
    except Exception as exc:
        await update.message.reply_text(f"❌ Không lấy được dữ liệu: {exc}")
        return

    if not pages:
        await update.message.reply_text("Chưa có feature request nào khớp điều kiện.")
        return

    lines = ["💡 <b>Feature requests</b>", ""]
    buttons = []
    for page in pages[:20]:
        lines.append(nc.format_feature_line(page))
        short_id = nc.get_short_id(page, config.FEATURE_PROPS["id"])
        title = nc.get_title(page, config.FEATURE_PROPS["title"])
        buttons.append([InlineKeyboardButton(
            f"{short_id} · {title[:28]}", url=nc.page_url(page["id"])
        )])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


# ------------------------------------------------------------------ /status

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("Chỉ admin mới đổi được trạng thái.")
        return
    if not context.args:
        await update.message.reply_text(
            "Cú pháp: <code>/status BUG-12</code> hoặc <code>/status FR-3</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    raw = context.args[0].strip().upper()
    is_bug = not raw.startswith("FR")

    db_id = config.BUG_DB_ID if is_bug else config.FEATURE_DB_ID
    props = config.BUG_PROPS if is_bug else config.FEATURE_PROPS
    statuses = config.BUG_STATUSES if is_bug else config.FEATURE_STATUSES

    await update.message.chat.send_action("typing")
    page = await nc.find_by_short_id(db_id, props["id"], raw)
    if not page:
        await update.message.reply_text(f"Không tìm thấy {raw}.")
        return

    title = nc.get_title(page, props["title"])
    current = nc.get_prop(page, props["status"])
    prefix = "b" if is_bug else "f"

    rows = [
        [InlineKeyboardButton(
            f"{config.STATUS_EMOJI.get(s, '')} {s}",
            callback_data=f"st|{prefix}|{page['id']}|{i}",
        )]
        for i, s in enumerate(statuses) if s != current
    ]
    rows.append([InlineKeyboardButton("📄 Mở trong Notion", url=nc.page_url(page["id"]))])

    await update.message.reply_text(
        f"<b>{raw}</b> {html.escape(title)}\n"
        f"Hiện tại: {config.STATUS_EMOJI.get(current, '')} <b>{current}</b>\n\n"
        f"Chọn trạng thái mới:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def on_status_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not _is_admin(update):
        await query.answer("Chỉ admin mới đổi được trạng thái.", show_alert=True)
        return

    try:
        _, kind, page_id, idx = query.data.split("|")
        statuses = config.BUG_STATUSES if kind == "b" else config.FEATURE_STATUSES
        props = config.BUG_PROPS if kind == "b" else config.FEATURE_PROPS
        new_status = statuses[int(idx)]
    except (ValueError, IndexError):
        await query.edit_message_text("Dữ liệu nút không hợp lệ.")
        return

    try:
        page = await nc.update_status(page_id, props["status"], new_status)
    except Exception as exc:
        await query.edit_message_text(f"❌ Cập nhật thất bại: {exc}")
        return

    short_id = nc.get_short_id(page, props["id"])
    title = nc.get_title(page, props["title"])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📄 Mở trong Notion", url=nc.page_url(page_id))
    ]])
    await query.edit_message_text(
        f"✅ <b>{short_id}</b> {html.escape(title)}\n"
        f"→ {config.STATUS_EMOJI.get(new_status, '')} <b>{new_status}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )

    # Báo lại cho người report nếu bug đã fix xong
    reporter_chat = nc.get_prop(page, props["telegram_id"])
    done = new_status in ("Đã fix", "Hoàn thành")
    if done and reporter_chat and reporter_chat != str(update.effective_chat.id):
        try:
            await context.bot.send_message(
                reporter_chat,
                f"🎉 <b>{short_id}</b> {html.escape(title)}\n"
                f"đã chuyển sang <b>{new_status}</b>. Cảm ơn báo cáo của bạn!",
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        except Exception:
            log.info("Không gửi được thông báo tới %s", reporter_chat)


# ------------------------------------------------------------------ /me

async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    me = _reporter_name(update)
    await update.message.chat.send_action("typing")

    bugs = await nc.query_bugs(limit=50)
    feats = await nc.query_features(limit=50)

    mine_b = [p for p in bugs if nc.get_prop(p, config.BUG_PROPS["reporter"]) == me]
    mine_f = [p for p in feats if nc.get_prop(p, config.FEATURE_PROPS["reporter"]) == me]

    if not mine_b and not mine_f:
        await update.message.reply_text("Bạn chưa gửi bug hay feature nào.")
        return

    lines = [f"👤 <b>{html.escape(me)}</b>", ""]
    buttons = []
    if mine_b:
        lines.append("<b>Bug đã báo:</b>")
        for p in mine_b[:10]:
            lines.append(nc.format_bug_line(p))
            buttons.append([InlineKeyboardButton(
                nc.get_short_id(p, config.BUG_PROPS["id"]), url=nc.page_url(p["id"])
            )])
    if mine_f:
        lines.append("")
        lines.append("<b>Feature đã đề xuất:</b>")
        for p in mine_f[:10]:
            lines.append(nc.format_feature_line(p))

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        disable_web_page_preview=True,
    )


# ------------------------------------------------------------------ main

def main() -> None:
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    bug_conv = ConversationHandler(
        entry_points=[CommandHandler("bug", bug_start)],
        states={
            BUG_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bug_title)],
            BUG_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, bug_desc)],
            BUG_STEPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bug_steps)],
            BUG_SEVERITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, bug_severity)],
            BUG_VERSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, bug_version)],
            BUG_MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bug_module)],
            BUG_IMAGE: [MessageHandler(
                (filters.PHOTO | filters.Document.IMAGE | filters.TEXT) & ~filters.COMMAND,
                bug_image,
            )],
        },
        fallbacks=[CommandHandler("huy", cmd_cancel), CommandHandler("cancel", cmd_cancel)],
    )

    feat_conv = ConversationHandler(
        entry_points=[CommandHandler("feature", feat_start)],
        states={
            FEAT_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, feat_title)],
            FEAT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, feat_desc)],
            FEAT_IMPACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, feat_impact)],
            FEAT_EFFORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, feat_effort)],
            FEAT_IMAGE: [MessageHandler(
                (filters.PHOTO | filters.Document.IMAGE | filters.TEXT) & ~filters.COMMAND,
                feat_image,
            )],
        },
        fallbacks=[CommandHandler("huy", cmd_cancel), CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(bug_conv)
    app.add_handler(feat_conv)
    app.add_handler(CommandHandler("bugs", cmd_bugs))
    app.add_handler(CommandHandler("features", cmd_features))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CallbackQueryHandler(on_status_click, pattern=r"^st\|"))

    log.info("Bot đang chạy...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
