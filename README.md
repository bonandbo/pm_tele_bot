# VLTK Dev Tracker Bot

Bot Telegram log bug / feature request thẳng vào Notion, dùng chung trong group dev. Notion là nguồn dữ liệu duy nhất; bot chỉ là cửa vào tiện lợi.

## Notion đã dựng sẵn

Trang cha: **VLTK Dev Tracker**

| Database | ID |
|---|---|
| Bug Tracker | `37ac56fa3c584f08a332f7b927d1fbca` |
| Feature Requests | `eff48cff0d1d45a8a29d3195e0895338` |

**Bug Tracker** — Tiêu đề, Bug ID (BUG-1, BUG-2... tự tăng), Status, Severity, Priority, Version phát hiện, Version fix, Module, Người báo cáo, Người xử lý, Nhân vật, Cấp, Bản đồ, GitHub Issue, Ngày báo cáo, Cập nhật lần cuối, Telegram ID.
View: Bảng mặc định · **Tiến độ (Board)** gom theo Status · **Theo version** gom theo Version phát hiện.

**Feature Requests** — Tên feature, FR ID, Status, Impact, Effort, Version dự kiến, Module, Người đề xuất, Người phụ trách, Ngày đề xuất, Cập nhật lần cuối, Telegram ID.
View: Bảng mặc định · **Tiến độ (Board)** gom theo Status.

Trạng thái bug theo board 4 cột: **Mới báo cáo** (Open) → **Đang làm** → **Đã fix** (chờ QA confirm) → **Confirmed** (+ Không fix, Trùng lặp). Các trạng thái cũ Đã xác nhận / Đang fix / Chờ verify vẫn chọn được qua `/status`.
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

### 5. Thêm cột Notion (bắt buộc khi nâng cấp)

Thêm 4 cột vào Bug Tracker **trước khi** chạy bản này: `Nhân vật` (Text), `Cấp` (Number), `Bản đồ` (Text), `GitHub Issue` (URL). Tên phải khớp `BUG_PROPS` trong `config.py`.

Thiếu cột thì `/bug` trong chat riêng lỗi khi người báo điền Nhân vật / Cấp / Bản đồ (Notion từ chối cột không tồn tại), và bot không tạo GitHub issue.

### 6. GitHub issue tự động (tuỳ chọn)

Mỗi bug lưu vào Notion được LLM chuyển thành một GitHub issue theo template (Triệu chứng / Cách tái hiện / Môi trường / Log / Miền nghi ngờ) để AI agent đọc. Notion vẫn là nơi người đọc; issue ghi BUG-ID và link Notion, Notion lưu link issue ở cột **GitHub Issue**.

1. **Notion** — đã thêm 4 cột ở bước 5.
2. **GitHub token** — github.com → Settings → Developer settings → Fine-grained tokens → chỉ chọn repo nhận issue, quyền **Issues: Read and write** và **Contents: Read and write**.
3. **Branch ảnh** — ảnh bug được commit vào branch riêng để không làm bẩn `main`. Tạo một lần trong clone của repo đó:
   ```bash
   git switch --orphan bug-assets
   git commit --allow-empty -m "bug assets"
   git push -u origin bug-assets
   git switch main
   ```
4. **LLM** — lấy API key ở Alibaba Cloud Model Studio (DashScope) hoặc DeepSeek, điền `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
5. Điền `GITHUB_TOKEN`, `GITHUB_REPO` (`owner/repo`) vào `.env`, restart bot.

Thiếu bất kỳ biến nào ở trên thì tính năng tự tắt, bot chạy như cũ.

## Cách dùng

### Trong group — khai báo riêng tư (mặc định)

Gõ `/bug` (không kèm gì) trong group → bot đưa một nút bấm.

Bấm nút → Telegram mở **chat riêng với bot**, bot hỏi lần lượt từng trường (tiêu đề → mô tả → bước tái hiện → nhân vật → cấp → bản đồ → severity → version → module → ảnh). **Cả quá trình hỏi đáp chỉ mình người đó thấy.**

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

### GitHub issue — khi nào bot hỏi lại

Khai xong, bot báo `✅ Đã ghi nhận` rồi `⏳ Đang soạn GitHub issue…`:

- Nội dung đủ rõ → tạo issue luôn, trả nút **🐙 Mở GitHub issue**.
- Không rõ hiện tượng / không tái hiện được / thông tin mâu thuẫn → bot hỏi tối đa 3 câu. Trả lời trong 1 tin nhắn, hoặc `/boqua` để tạo issue với thông tin hiện có. Tối đa 2 vòng hỏi; bỏ đi quá 10 phút thì bot tự tạo issue từ bản nháp.
- Câu trả lời bổ sung được ghi vào mục **📜 Lịch sử** của page Notion.

Báo nhanh trong group (`/bug Tiêu đề | mô tả`): thẻ bug hiện ngay, vài giây sau bot gắn thêm nút **🐙 GitHub #34**, hoặc **✍️ Bổ sung cho GitHub issue** nếu cần hỏi thêm — bấm nút đó để trả lời trong chat riêng.

Nếu LLM/GitHub lỗi, bug vẫn nằm trong Notion. Admin chạy `/issue BUG-12` để tạo lại (không hỏi thêm).

### Lệnh chung

| Lệnh | Tác dụng |
|---|---|
| `/bugs` | Bug mới báo cáo (Open) — giống `/bugs -open` |
| `/bugs -fixing` | Bug đang làm |
| `/bugs -fixed` | Bug đã fix, chưa confirm |
| `/bugs -confirmed` | Bug đã confirm |
| `/bugs -fixed v1.2` | Kết hợp lọc theo version phát hiện |
| `/bugs Đang fix` | Bug theo tên trạng thái bất kỳ |
| `/features` | Toàn bộ feature request |
| `/features v1.2` | Feature theo version dự kiến |
| `/status BUG-12` | Hiện nút chọn trạng thái mới (admin) |
| `/status FR-3` | Tương tự cho feature |
| `/fixbug BUG-12` | Nhận fix: Open → Đang làm (admin) |
| `/fixed BUG-12 v1.3` | Đang làm → Đã fix, ghi Version fix = v1.3, nhắn người báo cáo nhờ verify (admin) |
| `/confirmed BUG-12 [v1.3]` | Đã fix → Confirmed, version tuỳ chọn (admin) |
| `/reopened BUG-12 lý do` | Đã fix → Open, lý do ghi vào comment Notion (admin) |
| `/issue BUG-12` | Tạo GitHub issue cho bug chưa có (admin) |
| `/boqua` | Đang bị hỏi bổ sung → tạo issue luôn (chat riêng) |
| `/me` | Bug/feature mình đã gửi |
| `/id` | Lấy chat ID + user ID |
| `/huy` | Huỷ phiên đang khai dở (chat riêng) |
| `/help` | Hướng dẫn |

Mọi danh sách đều kèm nút mở thẳng trang Notion tương ứng. `/bugs` mở đầu bằng dòng **số bug** ở trạng thái đó (đếm đủ, kể cả khi chỉ hiện 15 dòng đầu).

Khi admin chuyển bug sang **Đã fix** (hoặc feature sang **Hoàn thành**), bot tự nhắn lại nơi đã báo cáo.

### Tiến độ bug: 4 lệnh theo board

```
/fixbug BUG-44            Mới báo cáo → Đang làm
/fixed BUG-44 v1.3        Đang làm → Đã fix   (+ Version fix = v1.3)
/confirmed BUG-44 [v1.3]  Đã fix → Confirmed
/reopened BUG-44 lý do    Đã fix → Mới báo cáo (lý do ghi vào comment)
```

- Bug ID nhận cả `BUG-44`, `bug-44` hay `44`. Version thiếu chữ `v` được tự thêm (`1.3` → `v1.3`); không cần có sẵn trong `VERSIONS`, Notion tự tạo option.
- Bug **không** bị ép phải đang ở đúng cột nguồn — bot vẫn chuyển nhưng reply kèm `⚠️ nhảy từ …` để cả group thấy.
- Gõ lại khi bug đã ở cột đích thì bot báo "không đổi gì" (trừ khi kèm version mới → chỉ cập nhật Version fix).
- `/reopened` ghi lý do bằng **Notion comment**. Việc này cần integration bật *Insert comments* (notion.so/my-integrations → integration → Capabilities). Chưa bật thì bot tự ghi thành **callout** ở cuối body page, không mất lý do.
- `/bugs -open` / `-fixing` / `-fixed` / `-confirmed` liệt kê đúng 4 cột này; `/bugs` không cờ = `-open`.

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

Bot tải ảnh từ Telegram về rồi upload thẳng lên Notion (File Upload API) — ảnh nằm hẳn trong Notion, không hết hạn. Workspace Notion free giới hạn 5 MB/ảnh; ảnh lớn hơn bị bỏ qua và bot báo lại.

Khi tạo GitHub issue, ảnh được commit vào branch `bug-assets` của repo (`bug-assets/BUG-12/...`) và nhúng vào issue. Repo private thì chỉ người có quyền vào repo xem được.

**Bug cũ** (trước bản này) lưu ảnh dạng link Telegram — link đó chứa token bot và hết hạn sau một thời gian. Sau khi cập nhật, nên **revoke token bot** (BotFather → `/revoke`) rồi điền token mới vào `.env`.

## Thêm version mới

Khi ra build mới (vd v1.3):

1. Trong Notion, mở property **Version phát hiện** / **Version fix** / **Version dự kiến** → thêm option `v1.3`
2. Trong `config.py`, thêm `"v1.3"` vào `VERSIONS`
3. Restart bot

## Cấu trúc

```
vltk-bot/
├── bot.py             # handler Telegram: lệnh group, phiên chat riêng, nút bấm
├── notion_client.py   # gọi Notion API, upload ảnh, format dữ liệu
├── issue_pipeline.py  # Notion → LLM → ảnh → GitHub issue → ghi ngược Notion
├── llm_client.py      # gọi LLM OpenAI-compatible (Qwen/DeepSeek), parse JSON
├── github_client.py   # tạo issue, commit ảnh vào branch bug-assets
├── issue_template.py  # dựng markdown issue theo template
├── issue_models.py    # dataclass dùng chung
├── config.py          # biến môi trường, tên property, danh sách option
├── tests/             # pytest (python -m pytest tests)
├── requirements.txt
├── .env.example
└── README.md
```

Đổi tên cột trong Notion thì sửa `BUG_PROPS` / `FEATURE_PROPS` trong `config.py`, không phải sửa chỗ khác.
