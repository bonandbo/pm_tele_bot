# VLTK Dev Tracker Bot

Bot Telegram log bug / feature request thẳng vào Notion, dùng chung trong group dev. Notion là nguồn dữ liệu duy nhất; bot chỉ là cửa vào tiện lợi.

## Notion đã dựng sẵn

Trang cha: **VLTK Dev Tracker**

| Database | ID |
|---|---|
| Bug Tracker | `37ac56fa3c584f08a332f7b927d1fbca` |
| Feature Requests | `eff48cff0d1d45a8a29d3195e0895338` |

**Bug Tracker** — Tiêu đề, Bug ID (BUG-1, BUG-2... tự tăng), Status, Severity, Priority, Version phát hiện, Version fix, Module, Người báo cáo, Người xử lý, Ngày báo cáo, Cập nhật lần cuối, Telegram ID.
View: Bảng mặc định · **Tiến độ (Board)** gom theo Status · **Theo version** gom theo Version phát hiện.

**Feature Requests** — Tên feature, FR ID, Status, Impact, Effort, Version dự kiến, Module, Người đề xuất, Người phụ trách, Ngày đề xuất, Cập nhật lần cuối, Telegram ID.
View: Bảng mặc định · **Tiến độ (Board)** gom theo Status.

Trạng thái bug: Mới báo cáo → Đã xác nhận → Đang fix → Chờ verify → Đã fix (+ Không fix, Trùng lặp).
Trạng thái feature: Mới đề xuất → Đang xem xét → Đã duyệt → Đang làm → Hoàn thành (+ Từ chối, Hoãn lại).

## Cài đặt

### 1. Tạo bot Telegram

Chat với [@BotFather](https://t.me/BotFather) → `/newbot` → đặt tên → nhận token.

**Giữ nguyên Privacy Mode ở trạng thái Enabled (mặc định).** Bot chỉ cần nhận lệnh bắt đầu bằng `/` — vốn luôn được gửi tới bot dù privacy bật. Tắt privacy sẽ khiến bot đọc toàn bộ tin nhắn trong group, vừa thừa vừa nhạy cảm.

### 2. Tạo Notion integration

1. Vào https://www.notion.so/my-integrations → **New integration**
2. Chọn workspace, đặt tên (vd "VLTK Bot"), lấy **Internal Integration Secret** (`ntn_...`)
3. **Quan trọng:** mở trang **VLTK Dev Tracker** trong Notion → menu `···` góc phải trên → **Connections** → **Connect to** → chọn integration vừa tạo. Cả 2 database bên trong tự kế thừa quyền.

Bỏ qua bước 3 thì bot báo lỗi 404 khi gọi API — đây là lỗi hay gặp nhất.

### 3. Chạy bot

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# điền TELEGRAM_TOKEN và NOTION_TOKEN

python bot.py
```

### 4. Thêm bot vào group

1. Mở group → Add members → tìm `@tên_bot` → thêm vào
2. Gõ `/id` trong group → bot trả về **Chat ID** (số âm) và **User ID** của anh
3. Điền vào `.env`:
   - `ALLOWED_CHAT_IDS` = chat ID group (chặn bot bị lôi sang group lạ)
   - `ADMIN_USER_IDS` = user ID những người được đổi trạng thái
   - `ADMIN_CHAT_ID` = chat ID group, để bug báo từ chat riêng cũng hiện lên group
4. Restart bot

Bot **không cần** quyền admin trong group.

## Cách dùng

### Trong group — khai báo riêng tư (mặc định)

Gõ `/bug` (không kèm gì) trong group → bot đưa một nút bấm.

Bấm nút → Telegram mở **chat riêng với bot**, bot hỏi lần lượt từng trường (tiêu đề → mô tả → bước tái hiện → severity → version → module → ảnh). **Cả quá trình hỏi đáp chỉ mình người đó thấy.**

Khai xong, bot tự đăng thẻ kết quả vào đúng group ban đầu, kèm nút mở trang Notion.

```
[trong group]  User: /bug
               Bot:  🐛 Bấm nút bên dưới để khai báo bug.
                     [🐛 Khai báo bug (chat riêng)]

[chat riêng]   Bot:  Tiêu đề ngắn gọn của bug là gì?
               User: Rớt kết nối khi vào Tống Kim
               Bot:  Mô tả chi tiết bug?
               ...                        ← chỉ user này thấy
               Bot:  ✅ Đã ghi nhận.
                     Đã đăng vào group VLTK Dev.

[trong group]  Bot:  🐛 Bug mới
                     BUG-8 Rớt kết nối khi vào Tống Kim
                     🆕 Mới báo cáo · 🟠 Cao · 📦 v1.2 · 🧩 Server
                     báo bởi @dee
                     [📄 Mở trong Notion]
```

Nút trong group ai bấm cũng được — mỗi người có phiên riêng, không đụng nhau.

Lần đầu bấm nút, Telegram hiện màn hình Start của bot; bấm Start một lần là xong, các lần sau vào thẳng.

### Trong group — báo nhanh một dòng (tuỳ chọn)

Khi bug đơn giản, không cần khai đủ trường:

```
/bug Rớt kết nối Tống Kim | Client disconnect sau loading map ở server đông
/feature Auto-loot khi PK | Giảm thao tác nhặt đồ trong combat
```

Phần trước dấu `|` là tiêu đề, phần sau là mô tả. Không có `|` thì cả câu thành tiêu đề.

Cách này nội dung hiện công khai trong group, đổi lại bot đăng thẻ kèm nút bấm để bổ sung **Severity / Version / Module** ngay tại chỗ.

**Đính ảnh:** gửi ảnh vào group trước, rồi **reply vào ảnh đó** và gõ lệnh.

### Trong chat riêng — vào thẳng

Nhắn riêng cho bot rồi gõ `/bug` hoặc `/feature`. Giống luồng trên nhưng không đăng về group nào (vì không đi qua nút trong group).

Muốn kết quả vẫn hiện ở group dev thì điền `ADMIN_CHAT_ID` = chat ID group đó.

### Lệnh chung

| Lệnh | Tác dụng |
|---|---|
| `/bugs` | Bug chưa xử lý xong |
| `/bugs v1.2` | Bug của version 1.2 |
| `/bugs Đang fix` | Bug theo trạng thái |
| `/features` | Toàn bộ feature request |
| `/features v1.2` | Feature theo version dự kiến |
| `/status BUG-12` | Hiện nút chọn trạng thái mới (admin) |
| `/status FR-3` | Tương tự cho feature |
| `/me` | Bug/feature mình đã gửi |
| `/id` | Lấy chat ID + user ID |
| `/huy` | Huỷ phiên đang khai dở (chat riêng) |
| `/help` | Hướng dẫn |

Mọi danh sách đều kèm nút mở thẳng trang Notion tương ứng.

Khi admin chuyển bug sang **Đã fix** (hoặc feature sang **Hoàn thành**), bot tự nhắn lại nơi đã báo cáo.

## Vì sao phiên khai báo phải diễn ra ở chat riêng

Telegram **không có** tin nhắn chỉ hiện với một người trong group (kiểu ephemeral của Slack). Bot đăng gì vào group là cả group thấy.

Nếu cố cho luồng hỏi-đáp chạy thẳng trong group thì:

- phải tắt Privacy Mode → bot đọc toàn bộ hội thoại của group
- tin nhắn tán gẫu bình thường bị bot "nuốt" thành câu trả lời
- nhiều người khai cùng lúc → câu hỏi đè lên nhau, ai cũng thấy bàn phím của người khác
- toàn bộ quá trình hỏi đáp làm loãng group

Nên phiên được đẩy sang chat riêng qua deep link, mang theo chat ID group trong payload (`?start=bug_-1001234567890`). Khai xong bot dựa vào chat ID đó để đăng kết quả về đúng nơi.

Nhờ vậy **Privacy Mode giữ nguyên Enabled** — trong group bot chỉ nhận lệnh bắt đầu bằng `/`, không đọc hội thoại.

Phiên tự hết hạn sau 10 phút không thao tác (`conversation_timeout` trong `bot.py`).

## Deploy 24/7

**VPS (systemd)** — tạo `/etc/systemd/system/vltk-bot.service`:

```ini
[Unit]
Description=VLTK Dev Tracker Bot
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/vltk-bot
ExecStart=/home/YOUR_USER/vltk-bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vltk-bot
sudo journalctl -u vltk-bot -f    # xem log
```

**Railway / Render / Fly.io** — free tier đủ cho polling bot. Push repo, set biến môi trường trong dashboard, start command `python bot.py`.

Chỉ chạy **một** instance duy nhất. Hai instance cùng polling một token sẽ tranh update và bot lúc trả lời lúc không.

## Lưu ý về ảnh

Bot lưu ảnh dưới dạng **external URL** trỏ tới file server của Telegram. Chạy được ngay không cần cấu hình gì, nhưng link Telegram có thể hết hạn — ảnh cũ trong Notion sẽ hỏng.

Nếu cần ảnh vĩnh viễn, chọn một trong hai:

1. **Notion File Upload API** — tải ảnh từ Telegram về, `POST /v1/file_uploads` rồi đính vào block. Ảnh nằm hẳn trong Notion.
2. **Trung chuyển qua S3 / Cloudflare R2 / Imgur** — upload lên đó rồi nhét URL vĩnh viễn vào Notion.

Chỗ cần sửa: hàm `_photo_url()` trong `bot.py` và phần `image_urls` trong `notion_client.py`.

Nên quyết sớm — để lâu mới đổi thì ảnh cũ mất hết.

## Thêm version mới

Khi ra build mới (vd v1.3):

1. Trong Notion, mở property **Version phát hiện** / **Version fix** / **Version dự kiến** → thêm option `v1.3`
2. Trong `config.py`, thêm `"v1.3"` vào `VERSIONS`
3. Restart bot

## Cấu trúc

```
vltk-bot/
├── bot.py             # handler Telegram: lệnh group, phiên chat riêng, nút bấm
├── notion_client.py   # gọi Notion API, format dữ liệu
├── config.py          # biến môi trường, tên property, danh sách option
├── requirements.txt
├── .env.example
└── README.md
```

Đổi tên cột trong Notion thì sửa `BUG_PROPS` / `FEATURE_PROPS` trong `config.py`, không phải sửa chỗ khác.
