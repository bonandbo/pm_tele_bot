"""
Bot Telegram cho VLTK Dev Tracker — chạy được cả trong group lẫn chat riêng.

Trong GROUP (nhanh, một dòng):
  /bug Tiêu đề | mô tả chi tiết
  /feature Tên feature | mô tả
  → bot đăng thẻ kèm nút chỉnh Severity / Version / Module ngay tại chỗ.
  Reply vào 1 ảnh rồi gõ lệnh để đính ảnh đó.

Trong CHAT RIÊNG (đầy đủ, từng bước):
  /bug, /feature → hỏi lần lượt từng trường.

Xem & quản lý (cả hai nơi):
  /bugs [-open|-fixing|-fixed|-confirmed] [vX.Y], /features, /status <ID>, /me, /huy

Tiến độ bug theo 4 cột board (admin):
  /fixbug <ID>            Open → Đang làm
  /fixed <ID> <version>   Đang làm → Đã fix (+ Version fix)
  /confirmed <ID> [ver]   Đã fix → Confirmed
  /reopened <ID> <lý do>  Đã fix → Open (lý do ghi vào comment)
"""
import html
import logging
import re
from typing import Optional
import asyncio

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.error import NetworkError, TimedOut

import config
import notion_client as nc

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

# Trạng thái hội thoại (chỉ dùng trong chat riêng)
(
    BUG_TITLE, BUG_DESC, BUG_STEPS, BUG_SEVERITY,
    BUG_VERSION, BUG_MODULE, BUG_IMAGE,
) = range(7)
(
    FEAT_TITLE, FEAT_DESC, FEAT_IMPACT, FEAT_EFFORT, FEAT_IMAGE,
) = range(100, 105)

SKIP = "Bỏ qua"
BOT_USERNAME = ""  # điền lúc khởi động


# ================================================================ tiện ích

def _kb(options: list[str], cols: int = 2, add_skip: bool = False) -> ReplyKeyboardMarkup:
    rows = [options[i:i + cols] for i in range(0, len(options), cols)]
    if add_skip:
        rows.append([SKIP])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def _is_admin(update: Update) -> bool:
    if not config.ADMIN_USER_IDS:
        return True
    return update.effective_user.id in config.ADMIN_USER_IDS


def _is_group(update: Update) -> bool:
    return update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def _reporter_name(update: Update) -> str:
    u = update.effective_user
    return f"@{u.username}" if u.username else (u.full_name or str(u.id))


def _short(page_id: str) -> str:
    return page_id.replace("-", "")


_BUG_ID_RE = re.compile(r"^(?:BUG-?)?(\d+)$", re.IGNORECASE)


def _parse_bug_args(args: list[str]) -> tuple[Optional[str], str]:
    """['bug-44', 'v1.3'] → ('BUG-44', 'v1.3'). Nhận cả '44'. ID sai → (None, '')."""
    if not args:
        return None, ""
    m = _BUG_ID_RE.match(args[0].strip())
    if not m:
        return None, ""
    rest = " ".join(a.strip() for a in args[1:]).strip()
    return f"BUG-{int(m.group(1))}", rest


def _normalize_version(raw: str) -> Optional[str]:
    """'1.3' → 'v1.3', 'V0.0.8' → 'v0.0.8'. Rỗng hoặc không có chữ số → None."""
    v = (raw or "").strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    if not any(ch.isdigit() for ch in v):
        return None
    return f"v{v}"


async def _photo_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """Lấy URL ảnh từ chính tin nhắn, hoặc từ tin nhắn được reply."""
    for msg in (update.message, update.message.reply_to_message):
        if not msg:
            continue
        file_id = None
        if msg.photo:
            file_id = msg.photo[-1].file_id
        elif msg.document and (msg.document.mime_type or "").startswith("image/"):
            file_id = msg.document.file_id
        if file_id:
            f = await context.bot.get_file(file_id)
            return f.file_path
    return None


async def _guard_group(update: Update) -> bool:
    """Chặn group không nằm trong whitelist. True = được phép chạy tiếp."""
    if not _is_group(update) or not config.ALLOWED_CHAT_IDS:
        return True
    if update.effective_chat.id in config.ALLOWED_CHAT_IDS:
        return True
    await update.message.reply_text(
        "Bot chưa được cấp quyền dùng ở group này.\n"
        f"Chat ID: <code>{update.effective_chat.id}</code>",
        parse_mode=ParseMode.HTML,
    )
    return False


def _dm_button(action: str, label: str, origin_chat_id: int) -> InlineKeyboardMarkup:
    """Nút mở DM. Payload mang theo chat ID group để bot biết đăng kết quả về đâu."""
    payload = f"{action}_{origin_chat_id}"
    url = f"https://t.me/{BOT_USERNAME}?start={payload}"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)]])


async def _post_to_origin(
    context: ContextTypes.DEFAULT_TYPE,
    origin_chat_id: Optional[int],
    text: str,
    kb: InlineKeyboardMarkup,
) -> Optional[str]:
    """Đăng thẻ kết quả về group đã khởi tạo phiên. Trả về tên group nếu thành công."""
    if not origin_chat_id:
        return None
    try:
        await context.bot.send_message(
            origin_chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb
        )
        chat = await context.bot.get_chat(origin_chat_id)
        return chat.title or str(origin_chat_id)
    except Exception:
        log.warning("Không đăng được kết quả về chat %s", origin_chat_id)
        return None


# ================================================================ thẻ hiển thị

def _bug_card(page: dict) -> tuple[str, InlineKeyboardMarkup]:
    p = config.BUG_PROPS
    pid = _short(page["id"])
    short_id = nc.get_short_id(page, p["id"])
    title = nc.get_title(page, p["title"])
    status = nc.get_prop(page, p["status"])
    sev = nc.get_prop(page, p["severity"])
    ver = nc.get_prop(page, p["version_found"])
    mod = nc.get_prop(page, p["module"])
    reporter = nc.get_prop(page, p["reporter"])

    meta = []
    if status:
        meta.append(f"{config.STATUS_EMOJI.get(status, '')} {status}".strip())
    meta.append(f"{config.SEVERITY_EMOJI.get(sev, '⚪')} {sev}" if sev else "⚪ chưa rõ mức độ")
    if ver:
        meta.append(f"📦 {ver}")
    if mod:
        meta.append(f"🧩 {mod}")

    text = (
        f"🐛 <b>{short_id}</b> {html.escape(title)}\n"
        f"<i>{' · '.join(meta)}</i>"
    )
    if reporter:
        text += f"\n<i>báo bởi {html.escape(reporter)}</i>"

    rows = []
    if not sev:
        rows.append([
            InlineKeyboardButton(f"{config.SEVERITY_EMOJI[s]} {s}", callback_data=f"sv|{pid}|{i}")
            for i, s in enumerate(config.SEVERITIES)
        ])
    if not ver:
        rows.append([
            InlineKeyboardButton(v, callback_data=f"vr|{pid}|{i}")
            for i, v in enumerate(config.VERSIONS)
        ])
    if not mod:
        rows.append([InlineKeyboardButton("🧩 Chọn module", callback_data=f"mx|{pid}|0")])
    rows.append([InlineKeyboardButton("📄 Mở trong Notion", url=nc.page_url(page["id"]))])
    return text, InlineKeyboardMarkup(rows)


def _feature_card(page: dict) -> tuple[str, InlineKeyboardMarkup]:
    p = config.FEATURE_PROPS
    short_id = nc.get_short_id(page, p["id"])
    title = nc.get_title(page, p["title"])
    status = nc.get_prop(page, p["status"])
    impact = nc.get_prop(page, p["impact"])
    effort = nc.get_prop(page, p["effort"])
    reporter = nc.get_prop(page, p["reporter"])

    meta = [f"{config.STATUS_EMOJI.get(status, '')} {status}".strip()]
    if impact:
        meta.append(f"Impact: {impact}")
    if effort:
        meta.append(f"Effort: {effort}")

    text = f"💡 <b>{short_id}</b> {html.escape(title)}\n<i>{' · '.join(meta)}</i>"
    if reporter:
        text += f"\n<i>đề xuất bởi {html.escape(reporter)}</i>"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📄 Mở trong Notion", url=nc.page_url(page["id"]))
    ]])
    return text, kb


# ================================================================ /start, /help

HELP_GROUP = (
    "<b>VLTK Dev Tracker Bot</b>\n\n"
    "<b>Khai báo (riêng tư):</b>\n"
    "/bug — bot hỏi từng bước trong chat riêng, xong đăng kết quả vào group\n"
    "/feature — tương tự cho đề xuất tính năng\n\n"
    "<b>Báo nhanh ngay tại group:</b>\n"
    "<code>/bug Tiêu đề | mô tả chi tiết</code>\n"
    "<code>/feature Tên feature | mô tả</code>\n"
    "Reply vào một ảnh rồi gõ lệnh để đính ảnh đó.\n\n"
    "<b>Xem danh sách:</b>\n"
    "/bugs — bug mới báo cáo (mặc định -open)\n"
    "/bugs -fixing · -fixed · -confirmed — theo cột board\n"
    "/bugs -fixed v1.2 — kết hợp lọc version\n"
    "/features — feature request\n"
    "/me — những gì mình đã gửi\n\n"
    "<b>Admin — tiến độ bug:</b>\n"
    "/fixbug BUG-44 — nhận fix (Open → Đang làm)\n"
    "/fixed BUG-44 v1.3 — đã fix ở version đó (→ Đã fix)\n"
    "/confirmed BUG-44 [v1.3] — QA xác nhận (→ Confirmed)\n"
    "/reopened BUG-44 lý do — vẫn lỗi, mở lại (→ Open)\n"
    "/status BUG-12 — chọn trạng thái bất kỳ."
)

HELP_PRIVATE = (
    "<b>VLTK Dev Tracker Bot</b>\n\n"
    "🐛 /bug — báo bug (hỏi từng bước)\n"
    "💡 /feature — đề xuất tính năng\n"
    "📋 /bugs [-open|-fixing|-fixed|-confirmed] — danh sách bug\n"
    "📋 /features — danh sách feature\n"
    "🔄 /status &lt;ID&gt; — đổi trạng thái (admin)\n"
    "🔨 /fixbug BUG-44 · 🎉 /fixed BUG-44 v1.3\n"
    "☑️ /confirmed BUG-44 · 🔁 /reopened BUG-44 lý do\n"
    "👤 /me — những gì mình đã gửi\n"
    "❌ /huy — huỷ thao tác đang làm\n\n"
    "Trong group có thể báo nhanh một dòng:\n"
    "<code>/bug Tiêu đề | mô tả</code>"
)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        HELP_GROUP if _is_group(update) else HELP_PRIVATE,
        parse_mode=ParseMode.HTML,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Đã huỷ.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ================================================================ tạo nhanh trong group

def _split_args(text: str) -> tuple[str, str]:
    """'Tiêu đề | mô tả' → ('Tiêu đề', 'mô tả'). Không có '|' thì mô tả rỗng."""
    if "|" in text:
        head, _, tail = text.partition("|")
        return head.strip(), tail.strip()
    return text.strip(), ""


async def quick_bug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_group(update):
        return
    raw = " ".join(context.args).strip() if context.args else ""
    chat_id = update.effective_chat.id

    # Không kèm nội dung → mở phiên riêng tư trong DM, xong bot đăng kết quả về group
    if not raw:
        await update.message.reply_text(
            "🐛 Bấm nút bên dưới để khai báo bug.\n\n"
            "Bot sẽ hỏi từng bước <b>trong chat riêng</b> — không ai trong group thấy. "
            "Khai xong, bot tự đăng thẻ kết quả vào đây.\n\n"
            "<i>Hoặc báo nhanh một dòng:</i>\n"
            "<code>/bug Tiêu đề | mô tả</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=_dm_button("bug", "🐛 Khai báo bug (chat riêng)", chat_id),
        )
        return

    title, desc = _split_args(raw)
    urls = []
    url = await _photo_url(update, context)
    if url:
        urls.append(url)

    await update.message.chat.send_action("typing")
    try:
        page = await nc.create_bug(
            title=title,
            description=desc,
            reporter=_reporter_name(update),
            telegram_id=str(update.effective_chat.id),
            image_urls=urls,
        )
    except Exception as exc:
        log.exception("Tạo bug thất bại")
        await update.message.reply_text(f"❌ Lỗi khi lưu vào Notion: {exc}")
        return

    text, kb = _bug_card(page)
    hint = "" if urls else "\n\n<i>Bấm nút bên dưới để bổ sung thông tin.</i>"
    await update.message.reply_text(
        f"✅ Đã ghi nhận\n\n{text}{hint}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def quick_feature(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_group(update):
        return
    raw = " ".join(context.args).strip() if context.args else ""
    chat_id = update.effective_chat.id

    if not raw:
        await update.message.reply_text(
            "💡 Bấm nút bên dưới để đề xuất tính năng.\n\n"
            "Bot hỏi từng bước <b>trong chat riêng</b>, khai xong sẽ đăng kết quả vào đây.\n\n"
            "<i>Hoặc đề xuất nhanh một dòng:</i>\n"
            "<code>/feature Tên feature | mô tả</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=_dm_button("feature", "💡 Đề xuất (chat riêng)", chat_id),
        )
        return

    title, desc = _split_args(raw)
    urls = []
    url = await _photo_url(update, context)
    if url:
        urls.append(url)

    await update.message.chat.send_action("typing")
    try:
        page = await nc.create_feature(
            title=title,
            description=desc,
            reporter=_reporter_name(update),
            telegram_id=str(update.effective_chat.id),
            image_urls=urls,
        )
    except Exception as exc:
        log.exception("Tạo feature thất bại")
        await update.message.reply_text(f"❌ Lỗi khi lưu vào Notion: {exc}")
        return

    text, kb = _feature_card(page)
    await update.message.reply_text(
        f"✅ Đã ghi nhận\n\n{text}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


# ================================================================ nút bổ sung field

async def on_field_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    kind, pid, idx = query.data.split("|")
    p = config.BUG_PROPS

    # Mở bảng chọn module
    if kind == "mx":
        await query.answer()
        rows = [
            [InlineKeyboardButton(m, callback_data=f"md|{pid}|{i}")
             for i, m in enumerate(config.MODULES[j:j + 2], start=j)]
            for j in range(0, len(config.MODULES), 2)
        ]
        rows.append([InlineKeyboardButton("↩️ Bỏ qua", callback_data=f"mn|{pid}|0")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(rows))
        return

    if kind == "mn":
        page = await nc.get_page(pid)
        text, kb = _bug_card(page)
        await query.answer()
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    try:
        if kind == "sv":
            value = config.SEVERITIES[int(idx)]
            prop_label = p["severity"]
            page = await nc.update_property(pid, prop_label, value)
        elif kind == "vr":
            value = config.VERSIONS[int(idx)]
            prop_label = p["version_found"]
            page = await nc.update_property(pid, prop_label, value)
        elif kind == "md":
            value = config.MODULES[int(idx)]
            prop_label = p["module"]
            page = await nc.update_multi_select(pid, prop_label, [value])
        else:
            await query.answer()
            return
    except Exception as exc:
        log.exception("Cập nhật field thất bại")
        await query.answer(f"Lỗi: {exc}", show_alert=True)
        return

    try:
        await nc.log_history(pid, f"{prop_label} = {value} · bởi {_reporter_name(update)}")
    except Exception:
        log.exception("Ghi lịch sử sửa field thất bại")

    await query.answer(f"Đã đặt: {value}")
    text, kb = _bug_card(page)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ================================================================ hội thoại đầy đủ (chat riêng)

async def start_or_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/start trong chat riêng.

    Payload dạng 'bug_-1001234567890' → vào thẳng hội thoại và nhớ group
    để đăng kết quả về đó khi xong.
    """
    payload = context.args[0].lower() if context.args else ""
    action, _, origin = payload.partition("_")

    origin_chat_id = None
    if origin.lstrip("-").isdigit():
        origin_chat_id = int(origin)

    if action == "bug":
        state = await bug_start(update, context)
        context.user_data["origin_chat"] = origin_chat_id
        return state
    if action == "feature":
        state = await feat_start(update, context)
        context.user_data["origin_chat"] = origin_chat_id
        return state

    await update.message.reply_text(HELP_PRIVATE, parse_mode=ParseMode.HTML)
    return ConversationHandler.END


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
    await update.message.reply_text("Mức độ nghiêm trọng?", reply_markup=_kb(config.SEVERITIES))
    return BUG_SEVERITY


async def bug_severity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    context.user_data["severity"] = val if val in config.SEVERITIES else None
    await update.message.reply_text(
        "Phát hiện ở version nào?", reply_markup=_kb(config.VERSIONS, add_skip=True)
    )
    return BUG_VERSION


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
    url = await _photo_url(update, context)
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

    text, kb = _bug_card(page)
    origin = d.get("origin_chat")
    group_name = await _post_to_origin(context, origin, f"🐛 <b>Bug mới</b>\n\n{text}", kb)

    confirm = f"✅ Đã ghi nhận\n\n{text}"
    if group_name:
        confirm += f"\n\n<i>Đã đăng vào group {html.escape(group_name)}.</i>"
    await update.message.reply_text(confirm, parse_mode=ParseMode.HTML, reply_markup=kb)

    # Thông báo tới ADMIN_CHAT_ID nếu chưa trùng với group vừa đăng
    if (
        config.ADMIN_CHAT_ID
        and str(update.effective_chat.id) != config.ADMIN_CHAT_ID
        and str(origin or "") != config.ADMIN_CHAT_ID
    ):
        try:
            await context.bot.send_message(
                config.ADMIN_CHAT_ID,
                f"🐛 <b>Bug mới</b>\n\n{text}",
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        except Exception:
            log.warning("Không gửi được thông báo tới ADMIN_CHAT_ID")

    context.user_data.clear()
    return ConversationHandler.END


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
        "Có ảnh tham khảo không? Không thì bấm Bỏ qua.",
        reply_markup=_kb([], add_skip=True),
    )
    return FEAT_IMAGE


async def feat_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    urls = []
    url = await _photo_url(update, context)
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

    text, kb = _feature_card(page)
    origin = d.get("origin_chat")
    group_name = await _post_to_origin(context, origin, f"💡 <b>Feature mới</b>\n\n{text}", kb)

    confirm = f"✅ Đã ghi nhận\n\n{text}"
    if group_name:
        confirm += f"\n\n<i>Đã đăng vào group {html.escape(group_name)}.</i>"
    await update.message.reply_text(confirm, parse_mode=ParseMode.HTML, reply_markup=kb)

    context.user_data.clear()
    return ConversationHandler.END


# ================================================================ danh sách

# Cờ /bugs → key trong config.BUG_FLOW
_BUGS_FLAGS = {"open": "open", "fixing": "doing", "fixed": "fixed", "confirmed": "confirmed"}
_BUGS_OPEN_ALIASES = ("open", "mo", "mở", "chua", "chưa")
_BUGS_MAX_LINES = 15

BUGS_USAGE = (
    "Cú pháp: <code>/bugs [-open|-fixing|-fixed|-confirmed] [v1.3]</code>\n"
    "-open: mới báo cáo (mặc định) · -fixing: đang làm · "
    "-fixed: đã fix chưa confirm · -confirmed: đã confirm"
)


def _parse_bugs_args(args: list[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """/bugs [-open|-fixing|-fixed|-confirmed] [vX.Y] [tên trạng thái] → (status, version, error).

    Không có cờ → mặc định -open. Có error → caller reply usage.
    """
    status: Optional[str] = None
    version: Optional[str] = None
    words: list[str] = []
    for a in args:
        a = a.strip()
        if not a:
            continue
        low = a.lower()
        if low.startswith("-"):
            key = low.lstrip("-")
            if key not in _BUGS_FLAGS:
                return None, None, f"Không hiểu cờ <code>{html.escape(a)}</code>."
            status = config.BUG_FLOW[_BUGS_FLAGS[key]]
        elif low in _BUGS_OPEN_ALIASES:
            status = config.BUG_FLOW["open"]
        elif low.startswith("v") and any(ch.isdigit() for ch in low):
            version = a
        else:
            words.append(low)
    if status is None and words:
        joined = " ".join(words)
        status = next((s for s in config.BUG_STATUSES if s.lower() in joined), None)
    return status or config.BUG_FLOW["open"], version, None


async def cmd_bugs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_group(update):
        return
    status, version, err = _parse_bugs_args(context.args or [])
    if err:
        await update.message.reply_text(f"{err}\n{BUGS_USAGE}", parse_mode=ParseMode.HTML)
        return

    await update.message.chat.send_action("typing")
    try:
        pages = await nc.query_bugs(status=status, version=version, limit=None)
    except Exception as exc:
        await update.message.reply_text(f"❌ Không lấy được dữ liệu: {exc}")
        return

    # Dòng đầu: số bug ở trạng thái đó (đếm đủ, không chỉ phần hiển thị)
    head = f"{config.STATUS_EMOJI.get(status, '🐛')} <b>{status}</b>: {len(pages)} bug"
    if version:
        head += f" · 📦 {html.escape(version)}"

    if not pages:
        await update.message.reply_text(f"{head} 🎉", parse_mode=ParseMode.HTML)
        return

    lines = [head, ""]
    buttons = []
    for page in pages[:_BUGS_MAX_LINES]:
        lines.append(nc.format_bug_line(page))
        short_id = nc.get_short_id(page, config.BUG_PROPS["id"])
        title = nc.get_title(page, config.BUG_PROPS["title"])
        buttons.append([InlineKeyboardButton(
            f"{short_id} · {title[:28]}", url=nc.page_url(page["id"])
        )])
    if len(pages) > _BUGS_MAX_LINES:
        lines.append("")
        lines.append(f"<i>… hiện {_BUGS_MAX_LINES}/{len(pages)}, xem đủ trong Notion</i>")
        buttons.append([InlineKeyboardButton("📋 Mở Bug Tracker", url=nc.bug_db_url())])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


async def cmd_features(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_group(update):
        return
    args = [a.strip() for a in context.args] if context.args else []
    joined = " ".join(args).lower()
    version = next((a for a in args if a.lower().startswith("v")), None)
    status = next((s for s in config.FEATURE_STATUSES if s.lower() in joined), None)

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
    for page in pages[:15]:
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


# ================================================================ /status

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_group(update):
        return
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
    pid = _short(page["id"])

    rows = [
        [InlineKeyboardButton(
            f"{config.STATUS_EMOJI.get(s, '')} {s}",
            callback_data=f"st|{prefix}|{pid}|{i}",
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

    if not _is_admin(update):
        await query.answer("Chỉ admin mới đổi được trạng thái.", show_alert=True)
        return
    await query.answer()

    try:
        _, kind, pid, idx = query.data.split("|")
        statuses = config.BUG_STATUSES if kind == "b" else config.FEATURE_STATUSES
        props = config.BUG_PROPS if kind == "b" else config.FEATURE_PROPS
        new_status = statuses[int(idx)]
    except (ValueError, IndexError):
        await query.edit_message_text("Dữ liệu nút không hợp lệ.")
        return

    try:
        page = await nc.update_status(pid, props["status"], new_status)
    except Exception as exc:
        await query.edit_message_text(f"❌ Cập nhật thất bại: {exc}")
        return

    short_id = nc.get_short_id(page, props["id"])
    title = nc.get_title(page, props["title"])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📄 Mở trong Notion", url=nc.page_url(pid))
    ]])
    await query.edit_message_text(
        f"✅ <b>{short_id}</b> {html.escape(title)}\n"
        f"→ {config.STATUS_EMOJI.get(new_status, '')} <b>{new_status}</b>\n"
        f"<i>đổi bởi {html.escape(_reporter_name(update))}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )

    if new_status in ("Đã fix", "Hoàn thành"):
        await _notify_reporter(
            update, context, page, props["telegram_id"],
            f"🎉 <b>{short_id}</b> {html.escape(title)}\n"
            f"đã chuyển sang <b>{new_status}</b>. Cảm ơn báo cáo của bạn!",
            kb,
        )


async def _notify_reporter(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: dict,
    telegram_id_prop: str,
    text: str,
    kb: InlineKeyboardMarkup,
) -> None:
    """Nhắn về nơi đã báo cáo (Telegram ID lưu trong Notion), trừ khi chính là chat hiện tại."""
    reporter_chat = nc.get_prop(page, telegram_id_prop)
    if not reporter_chat or reporter_chat == str(update.effective_chat.id):
        return
    try:
        await context.bot.send_message(
            reporter_chat, text, parse_mode=ParseMode.HTML, reply_markup=kb
        )
    except Exception:
        log.info("Không gửi được thông báo tới %s", reporter_chat)


# ================================================================ tiến độ bug: /fixbug /fixed /confirmed /reopened

async def _move_prelude(
    update: Update, context: ContextTypes.DEFAULT_TYPE, usage: str
) -> tuple[Optional[str], str]:
    """Kiểm tra group + quyền admin, parse '<BugID> <phần còn lại>'.

    Trả (None, '') khi đã reply lỗi cho user — caller chỉ cần return.
    """
    if not await _guard_group(update):
        return None, ""
    if not _is_admin(update):
        await update.message.reply_text("Chỉ admin mới đổi được trạng thái.")
        return None, ""
    bug_id, rest = _parse_bug_args(context.args or [])
    if not bug_id:
        await update.message.reply_text(
            f"Cú pháp: <code>{html.escape(usage)}</code>", parse_mode=ParseMode.HTML
        )
        return None, ""
    return bug_id, rest


async def _move_bug(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    bug_id: str,
    *,
    target: str,
    expected_from: str,
    version: Optional[str] = None,
    reason: Optional[str] = None,
    notify_text: Optional[str] = None,
) -> None:
    """Lõi chung: chuyển bug sang cột `target`.

    Không ép bug phải đang ở `expected_from` — vẫn chuyển nhưng cảnh báo trong reply
    để cả group thấy nó nhảy cóc. `reason` (reopen) ghi vào comment Notion.
    `notify_text` nếu có sẽ nhắn về nơi đã báo cáo bug.
    """
    p = config.BUG_PROPS
    em = config.STATUS_EMOJI
    await update.message.chat.send_action("typing")

    page = await nc.find_by_short_id(config.BUG_DB_ID, p["id"], bug_id)
    if not page:
        await update.message.reply_text(f"Không tìm thấy {bug_id}.")
        return

    title = nc.get_title(page, p["title"])
    current = nc.get_prop(page, p["status"])
    head = f"<b>{bug_id}</b> {html.escape(title)}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📄 Mở trong Notion", url=nc.page_url(page["id"]))
    ]])

    if current == target and not version and not reason:
        await update.message.reply_text(
            f"{head}\nđang ở {em.get(target, '')} <b>{target}</b> rồi, không đổi gì.",
            parse_mode=ParseMode.HTML, reply_markup=kb,
        )
        return

    try:
        page = await nc.update_bug_status(page["id"], target, version)
    except Exception as exc:
        log.exception("Chuyển %s → %s thất bại", bug_id, target)
        await update.message.reply_text(f"❌ Cập nhật thất bại: {exc}")
        return

    hist = f"{current or '—'} → {target} · bởi {_reporter_name(update)}"
    if version:
        hist += f" · Version fix {version}"
    if reason:
        hist += f" · lý do: {reason}"
    try:
        await nc.log_history(page["id"], hist)
    except Exception:
        log.exception("Ghi lịch sử cho %s thất bại", bug_id)

    comment_kind = None
    if reason:
        try:
            comment_kind = await nc.add_comment(
                page["id"], f"🔁 Reopen bởi {_reporter_name(update)}: {reason}"
            )
        except Exception:
            log.exception("Ghi lý do reopen cho %s thất bại", bug_id)

    lines = [f"✅ {head}"]
    if current == target:
        lines.append(f"vẫn ở {em.get(target, '')} <b>{target}</b>")
    else:
        cur_label = f"{em.get(current, '')} {current}".strip() if current else "chưa có trạng thái"
        lines.append(f"{cur_label} → {em.get(target, '')} <b>{target}</b>")
        if current != expected_from:
            lines.append(f"⚠️ <i>nhảy từ {cur_label}, bình thường phải từ {expected_from}</i>")
    if version:
        lines.append(f"📦 Version fix: <b>{html.escape(version)}</b>")
    if reason:
        if comment_kind == "comment":
            lines.append(f"💬 Lý do: {html.escape(reason)}")
        elif comment_kind == "callout":
            lines.append(f"📝 Lý do (ghi vào body page): {html.escape(reason)}")
        else:
            lines.append(f"⚠️ Không ghi được lý do vào Notion: {html.escape(reason)}")
    lines.append(f"<i>đổi bởi {html.escape(_reporter_name(update))}</i>")

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb
    )

    if notify_text:
        await _notify_reporter(
            update, context, page, p["telegram_id"], f"{head}\n{notify_text}", kb
        )


async def cmd_fixbug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fixbug BUG-44 — nhận fix: Open → Đang làm."""
    bug_id, _ = await _move_prelude(update, context, "/fixbug BUG-44")
    if not bug_id:
        return
    flow = config.BUG_FLOW
    await _move_bug(update, context, bug_id, target=flow["doing"], expected_from=flow["open"])


async def cmd_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fixed BUG-44 v1.3 — Đang làm → Đã fix, ghi Version fix, nhắn người báo cáo."""
    bug_id, rest = await _move_prelude(update, context, "/fixed BUG-44 v1.3")
    if not bug_id:
        return
    version = _normalize_version(rest.split()[0]) if rest else None
    if not version:
        await update.message.reply_text(
            "Thiếu version fix. Cú pháp: <code>/fixed BUG-44 v1.3</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    flow = config.BUG_FLOW
    await _move_bug(
        update, context, bug_id,
        target=flow["fixed"], expected_from=flow["doing"], version=version,
        notify_text=f"🎉 đã fix ở <b>{html.escape(version)}</b>, nhờ verify giúp nhé.",
    )


async def cmd_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/confirmed BUG-44 [v1.3] — Đã fix → Confirmed. Version tuỳ chọn."""
    bug_id, rest = await _move_prelude(update, context, "/confirmed BUG-44 [v1.3]")
    if not bug_id:
        return
    version = _normalize_version(rest.split()[0]) if rest else None
    flow = config.BUG_FLOW
    await _move_bug(
        update, context, bug_id,
        target=flow["confirmed"], expected_from=flow["fixed"], version=version,
    )


async def cmd_reopened(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reopened BUG-44 <lý do> — Đã fix → Open, lý do ghi vào comment Notion."""
    bug_id, reason = await _move_prelude(update, context, "/reopened BUG-44 lý do")
    if not bug_id:
        return
    if not reason:
        await update.message.reply_text(
            "Thiếu lý do reopen. Cú pháp: <code>/reopened BUG-44 vẫn crash khi vào map</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    flow = config.BUG_FLOW
    await _move_bug(
        update, context, bug_id,
        target=flow["open"], expected_from=flow["fixed"], reason=reason,
    )


# ================================================================ /me, /id

async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_group(update):
        return
    me = _reporter_name(update)
    await update.message.chat.send_action("typing")

    bugs = await nc.query_bugs(limit=60)
    feats = await nc.query_features(limit=60)
    mine_b = [p for p in bugs if nc.get_prop(p, config.BUG_PROPS["reporter"]) == me]
    mine_f = [p for p in feats if nc.get_prop(p, config.FEATURE_PROPS["reporter"]) == me]

    if not mine_b and not mine_f:
        await update.message.reply_text(f"{me} chưa gửi bug hay feature nào.")
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


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lấy chat ID (điền vào ALLOWED_CHAT_IDS) và user ID (ADMIN_USER_IDS)."""
    await update.message.reply_text(
        f"Chat ID: <code>{update.effective_chat.id}</code>\n"
        f"User ID: <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


# ================================================================ main

async def _post_init(app: Application) -> None:
    global BOT_USERNAME
    me = await app.bot.get_me()
    BOT_USERNAME = me.username
    log.info("Bot @%s sẵn sàng", BOT_USERNAME)

    from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

    group_cmds = [
        BotCommand("bug", "Báo bug: /bug Tiêu đề | mô tả"),
        BotCommand("feature", "Đề xuất: /feature Tên | mô tả"),
        BotCommand("bugs", "Danh sách bug: -open|-fixing|-fixed|-confirmed"),
        BotCommand("features", "Danh sách feature"),
        BotCommand("status", "Đổi trạng thái (admin)"),
        BotCommand("fixbug", "Nhận fix: /fixbug BUG-44"),
        BotCommand("fixed", "Đã fix: /fixed BUG-44 v1.3"),
        BotCommand("confirmed", "QA xác nhận: /confirmed BUG-44"),
        BotCommand("reopened", "Mở lại: /reopened BUG-44 lý do"),
        BotCommand("me", "Những gì mình đã gửi"),
        BotCommand("help", "Hướng dẫn"),
    ]
    private_cmds = group_cmds + [BotCommand("huy", "Huỷ thao tác đang làm")]

    await app.bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())
    await app.bot.set_my_commands(group_cmds, scope=BotCommandScopeAllGroupChats())


def main() -> None:
    # Python 3.14 không còn tự tạo event loop — tạo thủ công cho PTB
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(_post_init)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .build()
    )

    private = filters.ChatType.PRIVATE

    # Hội thoại đầy đủ — chỉ chạy trong chat riêng để không nuốt tin nhắn group
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_or_deeplink, filters=private),
            CommandHandler("bug", bug_start, filters=private),
            CommandHandler("feature", feat_start, filters=private),
        ],
        states={
            BUG_TITLE: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, bug_title)],
            BUG_DESC: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, bug_desc)],
            BUG_STEPS: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, bug_steps)],
            BUG_SEVERITY: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, bug_severity)],
            BUG_VERSION: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, bug_version)],
            BUG_MODULE: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, bug_module)],
            BUG_IMAGE: [MessageHandler(
                private & (filters.PHOTO | filters.Document.IMAGE | filters.TEXT) & ~filters.COMMAND,
                bug_image,
            )],
            FEAT_TITLE: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, feat_title)],
            FEAT_DESC: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, feat_desc)],
            FEAT_IMPACT: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, feat_impact)],
            FEAT_EFFORT: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, feat_effort)],
            FEAT_IMAGE: [MessageHandler(
                private & (filters.PHOTO | filters.Document.IMAGE | filters.TEXT) & ~filters.COMMAND,
                feat_image,
            )],
        },
        fallbacks=[
            CommandHandler("huy", cmd_cancel),
            CommandHandler("cancel", cmd_cancel),
        ],
        conversation_timeout=600,
    )
    app.add_handler(conv)

    group = filters.ChatType.GROUPS
    app.add_handler(CommandHandler("bug", quick_bug, filters=group))
    app.add_handler(CommandHandler("feature", quick_feature, filters=group))
    app.add_handler(CommandHandler("start", cmd_help, filters=group))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("bugs", cmd_bugs))
    app.add_handler(CommandHandler("features", cmd_features))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler(["fixbug", "fizzbug"], cmd_fixbug))
    app.add_handler(CommandHandler("fixed", cmd_fixed))
    app.add_handler(CommandHandler("confirmed", cmd_confirmed))
    app.add_handler(CommandHandler("reopened", cmd_reopened))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CallbackQueryHandler(on_status_click, pattern=r"^st\|"))
    app.add_handler(CallbackQueryHandler(on_field_click, pattern=r"^(sv|vr|md|mx|mn)\|"))

    app.add_error_handler(on_error)

    log.info("Bot đang chạy...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error

    # Mạng chập chờn — không cần in traceback, chỉ ghi 1 dòng
    if isinstance(err, (TimedOut, NetworkError)):
        log.warning("Mạng chập chờn: %s", err)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "⚠️ Mạng chậm, tin nhắn vừa rồi chưa gửi được. Gửi lại giúp anh nhé."
                )
            except Exception:
                pass
        return

    log.exception("Lỗi không bắt được", exc_info=err)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ Có lỗi xảy ra, thử lại sau.")
        except Exception:
            pass

if __name__ == "__main__":
    main()
