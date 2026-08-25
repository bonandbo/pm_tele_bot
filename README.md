# VLTK Dev Tracker Bot

Bot Telegram log bug / feature request thẳng vào Notion. Notion là nguồn dữ liệu duy nhất; bot chỉ là cửa vào tiện lợi.

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

### 2. Tạo Notion integration

1. Vào https://www.notion.so/my-integrations → **New integration**
2. Chọn workspace, đặt tên (vd "VLTK Bot"), lấy **Internal Integration Secret** (`ntn_...`)
3. **Quan trọng:** mở trang **VLTK Dev Tracker** trong Notion → menu `···` góc phải trên → **Connections** → **Connect to** → chọn integration vừa tạo. Cả 2 database bên trong sẽ tự kế thừa quyền.

Bỏ qua bước 3 thì bot sẽ báo lỗi 404 khi gọi API.

### 3. Chạy bot

```bash
git clone <repo> && cd vltk-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# điền TELEGRAM_TOKEN và NOTION_TOKEN vào .env

python bot.py
```

### 4. Lấy ADMIN_USER_IDS (tuỳ chọn)

Chat với [@userinfobot](https://t.me/userinfobot) để lấy Telegram user ID của mình, điền vào `.env`. Nếu để trống, ai cũng đổi được status.

## Lệnh

| Lệnh | Tác dụng |
|---|---|
| `/bug` | Báo bug qua hội thoại từng bước (tiêu đề → mô tả → bước tái hiện → severity → version → module → ảnh) |
| `/feature` | Đề xuất feature (tên → mô tả → impact → effort → ảnh) |
| `/bugs` | Bug chưa xử lý xong |
| `/bugs v1.2` | Bug của version 1.2 |
| `/bugs Đang fix` | Bug theo trạng thái |
| `/features` | Toàn bộ feature request |
| `/features v1.2` | Feature theo version dự kiến |
| `/status BUG-12` | Hiện nút chọn trạng thái mới (admin) |
| `/status FR-3` | Tương tự cho feature |
| `/me` | Bug/feature mình đã gửi |
| `/huy` | Huỷ thao tác đang làm dở |

Mọi danh sách đều kèm nút bấm mở thẳng trang Notion tương ứng.

Khi admin chuyển bug sang **Đã fix** (hoặc feature sang **Hoàn thành**), bot tự nhắn lại cho người report qua Telegram ID đã lưu.

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

**Railway / Render / Fly.io** — free tier đủ dùng cho polling bot. Push repo, set biến môi trường trong dashboard, start command `python bot.py`.

## Lưu ý về ảnh

Bot đang lưu ảnh dưới dạng **external URL** trỏ tới file server của Telegram. Cách này chạy được ngay, không cần cấu hình gì thêm, nhưng link Telegram có thể hết hạn sau một thời gian — ảnh cũ trong Notion sẽ hỏng.

Nếu cần ảnh lưu vĩnh viễn, chọn một trong hai:

1. **Notion File Upload API** — tải ảnh từ Telegram về, `POST /v1/file_uploads` rồi đính vào block. Ảnh nằm hẳn trong Notion.
2. **Trung chuyển qua S3 / Cloudflare R2 / Imgur** — upload lên đó rồi nhét URL vĩnh viễn vào Notion.

Chỗ cần sửa là hàm `_file_url()` trong `bot.py` và phần `image_urls` trong `notion_client.py`.

## Thêm version mới

Khi ra build mới (vd v1.3):

1. Trong Notion, mở property **Version phát hiện** / **Version fix** / **Version dự kiến** → thêm option `v1.3`
2. Trong `bot.py`, sửa hàm `_known_versions()` để bot hiện nút chọn v1.3

## Cấu trúc

```
vltk-bot/
├── bot.py             # handler Telegram, hội thoại, lệnh
├── notion_client.py   # gọi Notion API, format dữ liệu
├── config.py          # biến môi trường, tên property, danh sách option
├── requirements.txt
├── .env.example
└── README.md
```

Đổi tên cột trong Notion thì sửa `BUG_PROPS` / `FEATURE_PROPS` trong `config.py`, không phải sửa chỗ khác.
