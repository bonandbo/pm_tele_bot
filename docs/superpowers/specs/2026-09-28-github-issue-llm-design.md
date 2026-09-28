# Thiết kế: Tự tạo GitHub issue từ bug Notion bằng LLM

Ngày: 2026-09-28 · Trạng thái: chờ duyệt

## 1. Mục tiêu

Mỗi bug báo qua bot vẫn vào Notion như hiện nay (cho người đọc). Sau khi lưu Notion, bot dùng LLM
chuyển nội dung bug thành một **GitHub issue theo template cố định** (cho AI agent đọc), ghi BUG-ID
của Notion vào issue.

LLM chỉ **hỏi lại user khi nội dung cốt lõi mơ hồ**; đủ rõ thì tạo issue luôn.

Kèm theo: chuyển ảnh bug khỏi link Telegram (hết hạn, và đang lộ token bot) sang Notion File Upload
và repo GitHub.

### Tiêu chí thành công

- Bug khai đủ và rõ → issue được tạo tự động, không hỏi gì thêm.
- Bug mơ hồ → bot hỏi tối đa 2 vòng, sau đó luôn tạo issue (không để mất).
- Mọi lỗi LLM/GitHub **không** ảnh hưởng việc lưu Notion; admin có đường tạo lại bằng `/issue`.
- Page Notion mới không còn chứa URL có token bot.
- Thiếu cấu hình LLM/GitHub → bot chạy y như trước.

### Ngoài phạm vi

- Đồng bộ trạng thái Notion ↔ GitHub (`/fixed`, `/confirmed`... chỉ cập nhật Notion như cũ).
- Tạo GitHub issue cho feature request.
- Di chuyển ảnh của bug cũ sang nơi lưu mới.
- Sửa thẻ bug đã đăng vào group từ luồng chat riêng để thêm link issue.
- Hàng đợi retry tự động.

## 2. Template issue

Template gốc bỏ dòng "Máy". Tiêu đề issue: `[BUG-12] <title>`. Body:

```markdown
> BUG-12 · Cao · v1.2 · Server · [Notion](<notion url>)

## Triệu chứng
<symptom>

![BUG-12 ảnh 1](https://github.com/<owner>/<repo>/blob/<assets-branch>/bug-assets/BUG-12/<block_id>.jpg?raw=true)

## Cách tái hiện
1. <step>
2. <step>

## Môi trường
- Nhân vật + cấp: <nhân vật> <cấp>
- Bản đồ: <bản đồ>

## Log liên quan
<log trong code fence, hoặc "_(không có)_">

## Nghi ngờ thuộc miền nào
<client|server|config|data|websdk, hoặc để trống>
```

Quy ước:
- Dòng đầu (`>`) gồm BUG-ID, Severity, Version phát hiện, Module, link Notion; trường rỗng bị bỏ.
- Trường Môi trường lấy **thẳng từ Notion**, không qua LLM. Trống → `_(chưa rõ)_`.
- Cách tái hiện rỗng → `_(chưa rõ)_`.
- Ảnh nằm cuối mục Triệu chứng. Ảnh commit lỗi → dòng `_(1 ảnh không tải được — xem trên Notion)_`.
- Label: lấy từ `GITHUB_LABELS`.

## 3. Thành phần

### Module mới

| File | Trách nhiệm | Phụ thuộc |
|---|---|---|
| `llm_client.py` | Gọi chat completion kiểu OpenAI-compatible (DashScope/Qwen, DeepSeek). `build_messages()` và `parse_draft()` là hàm thuần; `draft_issue()` gọi mạng. | `httpx`, `config` |
| `issue_template.py` | `render_title()`, `render_body()` — hàm thuần, ghép markdown theo mục 2. | không |
| `github_client.py` | `create_issue(title, body, labels)`, `put_asset(path, bytes)` qua GitHub REST. | `httpx`, `config` |
| `issue_pipeline.py` | Điều phối: đọc bug từ Notion → LLM → ảnh → tạo issue → ghi ngược Notion. Không biết gì về Telegram. | 4 module trên + `notion_client` |

`bot.py` chỉ lo Telegram I/O, gọi `issue_pipeline`.

### Kiểu dữ liệu (dataclass trong `issue_models.py` — module riêng để `issue_template`, `llm_client`, `issue_pipeline` cùng import, không vòng)

```python
@dataclass
class BugInput:          # đọc từ Notion
    page_id: str
    bug_id: str          # "BUG-12"
    notion_url: str
    title: str
    description: str
    steps: str
    severity: str
    version: str
    modules: str
    character: str
    level: Optional[int]
    map_name: str
    images: list[tuple[str, str]]       # (block_id, url tải được)
    github_issue: str    # URL đã có, "" nếu chưa

@dataclass
class IssueFields:       # LLM trả về
    title: str
    symptom: str
    steps: list[str]
    log: str
    domain: str          # "" | client | server | config | data | websdk

@dataclass
class Draft:
    status: str          # "ready" | "need_info"
    questions: list[str] # rỗng khi ready; tối đa 3
    issue: IssueFields   # luôn có — bản nháp tốt nhất
```

### API của `issue_pipeline`

```python
def enabled() -> bool
async def load_bug(page_id: str) -> BugInput
async def draft(bug: BugInput, qa: list[tuple[str, str]], final: bool) -> Draft
async def publish(bug: BugInput, fields: IssueFields) -> str   # trả URL issue
class PipelineError(Exception)   # message thân thiện để bot hiện cho user
```

`publish()`:
1. Đọc lại page; cột `GitHub Issue` đã có → trả URL đó, không tạo mới.
2. Với mỗi ảnh: tải bytes → `put_asset("bug-assets/<BUG-ID>/<block_id bỏ gạch>.<ext>")` (đủ 32 ký tự để không trùng). File đã tồn tại
   (GitHub trả 422) → coi như đã có, dùng lại đường dẫn. Lỗi khác → đánh dấu ảnh lỗi, tiếp tục.
3. `render_title` + `render_body` → `create_issue`.
4. `set_github_issue(page_id, url)` + `log_history(page_id, "Tạo GitHub issue #<n>")`.
   Lỗi ở bước 4 chỉ log warning (issue đã tạo).

### Sửa file cũ

**`config.py`**
- `BUG_PROPS` thêm: `"character": "Nhân vật"`, `"level": "Cấp"`, `"map": "Bản đồ"`, `"github_issue": "GitHub Issue"`.
- Biến môi trường mới (đều **không bắt buộc**):

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `LLM_BASE_URL` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | DeepSeek: `https://api.deepseek.com` |
| `LLM_API_KEY` | — | |
| `LLM_MODEL` | — | Không hard-code tên model |
| `GITHUB_TOKEN` | — | Fine-grained, 1 repo, Issues: write + Contents: write |
| `GITHUB_REPO` | — | `owner/repo` |
| `GITHUB_LABELS` | `bug` | Cách nhau dấu phẩy |
| `GITHUB_ASSETS_BRANCH` | `bug-assets` | Tạo tay 1 lần |

- `GITHUB_ENABLED = all(LLM_API_KEY, LLM_MODEL, GITHUB_TOKEN, GITHUB_REPO)`.

**`notion_client.py`**
- `create_bug(...)` nhận thêm `character`, `level`, `map_name`; nhận `images: list[tuple[bytes, str, str]]`
  (bytes, filename, content_type) thay cho `image_urls`.
- `create_feature(...)` cũng đổi sang `images` (để bịt lộ token cho cả feature).
- Mới: `upload_file(data, filename, content_type) -> str` (file_upload id) qua
  `POST /v1/file_uploads` → `POST /v1/file_uploads/{id}/send` (multipart). Khối ảnh:
  `{"type": "image", "image": {"type": "file_upload", "file_upload": {"id": ...}}}`.
- Mới: `set_github_issue(page_id, url)` (property kiểu URL).
- Mới: `read_bug_body(page_id) -> (description, steps, images)` — đọc block con: paragraph dưới heading
  "Mô tả" / "Bước tái hiện", và mọi khối `image` (`file` → `image.file.url`; `external` → `image.external.url`).
  Phần parse block tách thành hàm thuần `parse_bug_blocks(blocks)` để test.

**`bot.py`**
- `_photo_url()` → `_photo_file()` trả `(bytes, filename, content_type)` qua `download_as_bytearray()`.
  Không còn đưa `file_path` (chứa token) vào Notion.
- Ảnh > 5 MB (giới hạn Notion free) → bỏ ảnh, báo user "ảnh quá lớn, không đính kèm".
- Không bật `concurrent_updates` (sẽ khiến tin nhắn gửi trong lúc chờ LLM bị hiểu nhầm là câu trả lời
  của bước cũ → tạo bug trùng). Thay vào đó các handler chậm (`bug_image`, `bug_clarify`, `/boqua`,
  `start_or_deeplink`, `/issue`) đặt `block=False` để không chặn user khác, và ConversationHandler có
  state `ConversationHandler.WAITING` trả lời "⏳ Bot đang xử lý…" cho tin nhắn đến trong lúc chờ.

Ghi chú khi implement: xác nhận File Upload API chạy với `Notion-Version: 2022-06-28` đang dùng;
nếu không, chỉ các request file upload dùng version mới hơn.

## 4. LLM

**Gọi API**: `POST {LLM_BASE_URL}/chat/completions`, `response_format={"type": "json_object"}`,
`temperature=0.2`, timeout 60s.

**Tin nhắn user gửi LLM** gồm: tiêu đề, mô tả, bước tái hiện, severity, version, module, và các cặp
(câu hỏi, trả lời) của vòng trước. **Không** gửi nhân vật/cấp/bản đồ.
Vòng cuối (`final=True`) thêm dòng: "Đây là lượt cuối: bắt buộc status=ready, không hỏi thêm."

**System prompt** (tiếng Việt) nêu:
- Vai trò: chuyển báo cáo bug game (VLTK) thành issue cho AI agent đọc.
- Định dạng JSON đầu ra (mục 3, `Draft`).
- Không bịa. `log` chỉ điền khi user dán log. `domain` chỉ điền khi rõ ràng, không thì `""`.
- Giải thích 5 miền: client / server / config / data / websdk.
- **Chỉ `need_info` khi**: không rõ hiện tượng sai là gì; hoặc người khác đọc các bước không tái hiện được;
  hoặc thông tin mâu thuẫn.
- **Không hỏi** về nhân vật, cấp, bản đồ, log, miền nghi ngờ.
- Tối đa 3 câu hỏi, ngắn, tiếng Việt. Luôn điền `issue` với bản nháp tốt nhất.
- Giữ tiếng Việt, tiêu đề ngắn.

**`parse_draft(text)`**:
- Bóc khỏi ```json fence nếu có.
- `status` ngoài {ready, need_info} → lỗi. `need_info` mà `questions` rỗng → coi là `ready`.
- `domain` ngoài tập cho phép → `""`. `questions` cắt còn 3. `steps` chấp nhận list hoặc chuỗi nhiều dòng.
- `title` rỗng → dùng tiêu đề Notion.
- JSON hỏng → `LLMError`. `draft_issue()` thử lại 1 lần rồi mới ném lỗi.

**Số vòng**: `MAX_CLARIFY_ROUNDS = 2`. Lần gọi đầu `final=False`. Sau mỗi vòng user trả lời,
`final = (số vòng đã hỏi >= 2)`. Tối đa 3 lần gọi LLM/bug. Khi `final=True` mà LLM vẫn trả `need_info`,
`draft()` ép thành `ready` và dùng `issue` kèm theo.

## 5. Luồng Telegram

### 5.1 Khai bug trong chat riêng

State mới: `BUG_CHAR`, `BUG_LEVEL`, `BUG_MAP`, `BUG_CLARIFY`.

```
Tiêu đề → Mô tả → Bước tái hiện → Nhân vật → Cấp → Bản đồ → Severity → Version → Module → Ảnh
```

- Nhân vật / Cấp / Bản đồ đều có nút Bỏ qua.
- Cấp: `_parse_level(text)` nhận số nguyên dương; sai → nhắc "Cấp là số, vd 90" và ở lại state.

Sau `bug_image` lưu Notion + đăng group (giữ nguyên hành vi cũ), nếu `GITHUB_ENABLED`:
1. Nhắn "⏳ Đang soạn GitHub issue…", `load_bug` → `draft(final=False)`.
2. `ready` → `publish` → "🐙 Đã tạo issue #34" + nút mở issue → END.
3. `need_info` → lưu `gh_page_id`, `gh_qa`, `gh_draft`, `gh_rounds=1` vào `user_data`; gửi câu hỏi
   đánh số trong 1 tin, kèm "Trả lời trong 1 tin nhắn, hoặc /boqua để tạo issue với thông tin hiện có."
   → `BUG_CLARIFY`.

Trong `BUG_CLARIFY`:
- Tin nhắn text → ghi `log_history("Bổ sung cho GitHub: <câu hỏi> → <trả lời>")` (các câu hỏi gộp,
  trả lời nguyên văn) → `draft(final=rounds>=2)` → như bước 2/3.
- `/boqua` → `publish(gh_draft.issue)` → END.
- `/huy` → END, không tạo issue (admin dùng `/issue` sau).
- Timeout 10 phút: handler `ConversationHandler.TIMEOUT` → nếu `user_data` có `gh_page_id` thì
  `publish(gh_draft.issue)` và nhắn kết quả cho user.

### 5.2 Báo nhanh trong group (`/bug Tiêu đề | mô tả`)

1. Trả thẻ bug như hiện nay (không chờ LLM).
2. Nếu `GITHUB_ENABLED`: chạy nền bằng `context.application.create_task(...)`: `load_bug` → `draft(final=False)`.
   - `ready` → `publish` → sửa reply_markup của thẻ: thêm nút "🐙 GitHub #34".
   - `need_info` → sửa thẻ: thêm nút "✍️ Bổ sung cho GitHub issue" = deep-link `?start=clarify_12`.
3. Lỗi → thêm dòng cảnh báo (mục 5.4) bằng reply ngắn.

### 5.3 Deep-link `clarify_<số>`

`start_or_deeplink` nhận `clarify_12` → `find_by_short_id("BUG-12")`:
- Không thấy → báo lỗi, END.
- Đã có issue → trả link, END.
- Còn lại → `load_bug` → `draft(final=False)` → như 5.1 bước 2/3. Ai bấm cũng được.
  Không lưu câu hỏi cũ — chạy lại từ Notion, nên restart bot không mất gì.

### 5.4 Lệnh `/issue BUG-12` (admin)

Dùng `_parse_bug_args` sẵn có. Chưa cấu hình → "GitHub issue chưa được cấu hình". Đã có issue → trả link.
Còn lại → `load_bug` → `draft(final=True)` → `publish` → trả link. Không hỏi lại.

### 5.5 Xử lý lỗi

- LLM timeout / JSON hỏng 2 lần / GitHub lỗi → `PipelineError` → bot nhắn:
  "⚠️ Chưa tạo được GitHub issue: <lý do>. Bug đã lưu Notion — admin chạy /issue BUG-12."
  và kết thúc phiên.
- Không bao giờ để lỗi pipeline làm hỏng phản hồi "✅ Đã ghi nhận" của Notion (gọi sau, bọc try/except).
- Trùng: kiểm tra cột `GitHub Issue` ngay trước khi tạo. Chấp nhận race hiếm khi 2 người bấm cùng lúc.

## 6. Cài đặt (cập nhật README)

1. Notion — thêm 4 cột vào Bug Tracker: `Nhân vật` (Text), `Cấp` (Number), `Bản đồ` (Text), `GitHub Issue` (URL).
2. GitHub — tạo fine-grained token (1 repo; Issues: RW, Contents: RW). Tạo branch rỗng:
   ```bash
   git switch --orphan bug-assets && git commit --allow-empty -m "bug assets" && git push -u origin bug-assets
   ```
3. `.env` — điền biến ở mục 3.
4. Sau khi deploy: **revoke token bot** (BotFather `/revoke`) vì token cũ nằm trong URL ảnh ở các page Notion cũ.
5. Mục "Lưu ý về ảnh" trong README viết lại theo cách lưu mới.

## 7. Kiểm thử

**pytest (thuần, không gọi mạng)**
- `issue_template`: đủ trường; thiếu môi trường/bước/log; có ảnh; có ảnh lỗi; dòng đầu bỏ trường rỗng.
- `llm_client.parse_draft`: JSON hợp lệ; bọc ```json; status sai; domain sai; need_info không có câu hỏi;
  >3 câu hỏi; steps dạng chuỗi; JSON hỏng.
- `llm_client.build_messages`: có/không có Q&A; `final=True` có dòng "lượt cuối".
- `notion_client.parse_bug_blocks`: fixture block Notion (heading, paragraph, image file/external).
- `bot._parse_level`, parse payload `clarify_12`.

**Smoke test tay** (repo + Notion thật):
1. Bug rõ ràng qua chat riêng → issue tạo luôn, Notion có link + dòng lịch sử.
2. Bug mơ hồ ("game lỗi") → bị hỏi; trả lời → issue; Notion có dòng "Bổ sung cho GitHub".
3. Bug mơ hồ, gõ `/boqua` → issue từ bản nháp.
4. Báo nhanh trong group → thẻ được sửa thêm nút GitHub hoặc Bổ sung; bấm Bổ sung → luồng hỏi trong DM.
5. `/issue BUG-x` cho bug chưa có issue và bug đã có issue.
6. Bug có ảnh → ảnh hiện trên Notion (không phải link Telegram) và trong issue.
7. Xoá `LLM_API_KEY` → bot chạy như cũ, `/issue` báo chưa cấu hình.
