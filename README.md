# Zalo Bot chia tiền nhóm 💸

Bot Zalo giúp nhóm bạn, phòng trọ hay nhóm đi du lịch ghi lại các khoản chi chung. Bot tự tính ai nợ ai, gợi ý cách trả với **ít lần chuyển khoản nhất** và tạo **mã QR VietQR** để chuyển đúng số tiền.

Bot chạy trên [Zalo Bot Platform](https://bot.zaloplatforms.com), là nền tảng bot chính thức của Zalo. Bot không tự động hóa tài khoản Zalo cá nhân.

## Ví dụ hội thoại

```
👤 /taoso Đà Lạt 2026
🤖 ✅ Đã tạo sổ "Đà Lạt 2026" và chọn làm sổ đang dùng.
   🔑 Mã mời: T5ZWJF

👤 /them Linh, Hòa
🤖 ✅ Đã thêm: Linh, Hòa

👤 /chi 1tr2 tiền phòng
🤖 ✅ #1 Nam trả 1.200.000đ cho tiền phòng
   Chia 3 người (Nam, Linh, Hòa), mỗi người 400.000đ

👤 (Linh) /chi 450k xăng cho tất cả trừ Hòa
🤖 ✅ #2 Linh trả 450.000đ cho xăng
   Chia 2 người (Nam, Linh), mỗi người 225.000đ

👤 /so
🤖 📒 Số dư sổ "Đà Lạt 2026":
   🟢 Nam: +575.000đ
   🔴 Linh: -175.000đ
   🔴 Hòa: -400.000đ

👤 /tatoan
🤖 💸 Cách trả gọn nhất (2 lần chuyển):
   1. Hòa → Nam: 400.000đ
   2. Linh → Nam: 175.000đ

👤 (Linh) /qr Nam
🤖 [ảnh QR] Quét mã để chuyển 175.000đ cho Nam.
```

## Các lệnh

Lệnh gõ có dấu hay không dấu đều được. Trong chat riêng có thể bỏ dấu `/`.

| Lệnh | Ý nghĩa |
|---|---|
| `/taoso <tên>` | Tạo sổ mới và nhận mã mời |
| `/vao <mã> [tên]` | Vào sổ của bạn bè |
| `/chonso [số]` | Xem và chuyển giữa các sổ |
| `/them Nam, Linh` | Thêm thành viên chỉ có tên (người không dùng bot) |
| `/thanhvien` | Danh sách thành viên |
| `/toila <tên>` | Nhận một tên có sẵn trong sổ là của mình |
| `/chi 300k lẩu` | Bạn trả, chia đều cho cả sổ |
| `/chi 1tr2 phòng cho Nam, Linh` | Chỉ chia cho những người được nêu tên |
| `/chi 450k xăng cho tất cả trừ Hòa` | Chia cho cả sổ, trừ những người được nêu tên |
| `/chiho Nam 200k cafe` | Ghi khoản do người khác trả |
| `/tra Linh 150k` | Ghi lại việc bạn đã trả nợ cho Linh |
| `/so` | Số dư từng người |
| `/tatoan` | Ai chuyển cho ai, bao nhiêu |
| `/qr Linh [số tiền]` | Ảnh QR để chuyển tiền cho Linh |
| `/taikhoan VCB 0123456789 NGUYEN VAN A` | Lưu tài khoản ngân hàng của bạn |
| `/lichsu [n]` | n khoản gần nhất |
| `/xoa <id>` | Xóa một khoản (sau đó gửi `/xoa <id> ok` để xác nhận) |
| `/thongke` | Thống kê chi tiêu trong tháng |

**Cách gõ số tiền:** `300k`, `1tr2` (1.200.000), `1.5tr`, `1,5tr`, `2 triệu`, `150.000`, `50 nghìn`, `1 củ`.

**Trong nhóm chat:** thêm bot vào nhóm, rồi nhắc tên bot kèm lệnh, ví dụ `@TênBot /chi 300k lẩu`. Mỗi nhóm có một sổ riêng, và ai gõ lệnh thì tự động được thêm vào sổ.

## Cài đặt và chạy

### 1. Tạo bot và lấy token
Đăng nhập [bot.zaloplatforms.com](https://bot.zaloplatforms.com) bằng tài khoản Zalo, tạo bot mới, rồi sao chép **Bot Token** (dạng `123456789:abc...`).

### 2. Cài đặt
```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # rồi điền ZALO_BOT_TOKEN
```

### 3. Chạy thử trên máy (polling, không cần tên miền)
```bash
python -m app.polling
```
Mở Zalo, nhắn `/help` cho bot.

### 4. Chạy production (webhook)
Webhook bắt buộc dùng HTTPS. Khi test, bạn có thể mở tunnel bằng [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) hoặc ngrok:

```bash
uvicorn app.main:app --port 8000
cloudflared tunnel --url http://localhost:8000   # cho ra https://xxx.trycloudflare.com
```

Điền vào `.env`:
```
WEBHOOK_URL=https://xxx.trycloudflare.com/webhook
WEBHOOK_SECRET=<chuỗi ngẫu nhiên 8-256 ký tự, VD: openssl rand -hex 24>
```

Rồi đăng ký webhook với Zalo:
```bash
python -m app.set_webhook          # đăng ký
python -m app.set_webhook --info   # kiểm tra
python -m app.set_webhook --delete # gỡ, để quay lại dùng polling
```

> Lưu ý: polling và webhook không chạy cùng lúc được. `app.polling` tự gỡ webhook khi khởi động.

### 5. Deploy bằng Docker
```bash
docker build -t zalo-chia-tien .
docker run -d --name zalo-bot --env-file .env -p 8000:8000 -v zalo-data:/app/data zalo-chia-tien
# hoặc chạy polling:
docker run -d --name zalo-bot --env-file .env -v zalo-data:/app/data zalo-chia-tien python -m app.polling
```
Có thể deploy lên Railway, Render, Fly.io hoặc VPS. Nhớ gắn ổ đĩa (volume) vào `/app/data` để không mất dữ liệu.

### Sao lưu dữ liệu
Dữ liệu nằm trong file SQLite `data/bot.db`:
```bash
sqlite3 data/bot.db ".backup backup-$(date +%F).db"
```
Muốn dùng Postgres thì cài thêm `psycopg[binary]` và đặt `DATABASE_URL=postgresql+psycopg://user:pass@host/db`.

## Chạy test
```bash
pip install -r requirements-dev.txt
pytest
```

## Cấu trúc code

```
app/
  config.py        Cấu hình (.env)
  zalo_client.py   Gọi Zalo Bot API và đọc update. Mọi chi tiết API nằm ở đây
  handlers.py      Nhận tin nhắn, gọi nghiệp vụ, soạn câu trả lời
  commands.py      Tách lệnh và tham số (/chi, /tra, "cho", "trừ"...)
  money.py         Đọc và hiển thị số tiền VND (luôn dùng số nguyên)
  text.py          Bỏ dấu, chuẩn hóa tên tiếng Việt
  models.py        Bảng dữ liệu (SQLAlchemy)
  db.py            Kết nối database
  services/
    ledger.py      Nghiệp vụ sổ: thành viên, khoản chi, số dư, thống kê
    settle.py      Thuật toán tất toán (greedy, không quá n-1 giao dịch)
    vietqr.py      Tạo link ảnh VietQR
  main.py          Server webhook (FastAPI)
  polling.py       Chạy bằng long polling
  set_webhook.py   Đăng ký/gỡ webhook
tests/             pytest, chạy offline hoàn toàn
```

**Một vài quyết định thiết kế:**
- Tiền luôn lưu bằng số nguyên VND. Khi chia không hết (VD 100.000 / 3), phần dư được cộng mỗi người 1đ theo thứ tự, nên tổng các phần luôn khớp với số tiền.
- Trả nợ A → B được lưu như một khoản do A trả mà B chịu toàn bộ. Nhờ vậy số dư chỉ cần một công thức (đã trả − phải chịu), và tổng số dư của sổ luôn bằng 0.
- Mỗi tin nhắn chỉ được xử lý một lần (lưu theo `message_id`), nên Zalo có gửi lại thì cũng không bị ghi trùng.
- Webhook kiểm tra header `X-Bot-Api-Secret-Token` bằng phép so sánh thời gian hằng (`hmac.compare_digest`).
- Không ghi token bot vào log: log của `httpx` có chứa URL kèm token, nên đã bị chặn.

## Về Zalo Bot API
Code dựa trên tài liệu tại https://bot.zaloplatforms.com/docs:
- Địa chỉ gọi API: `https://bot-api.zaloplatforms.com/bot<TOKEN>/<method>`
- `getUpdates` trả về **một** update mỗi lần. Khi hết thời gian chờ mà không có tin mới, API trả mã lỗi 408.
- Một tin nhắn tối đa 2000 ký tự. Tin dài hơn sẽ được tự động cắt thành nhiều tin.

Nếu Zalo thay đổi API, chỉ cần sửa `app/zalo_client.py` (địa chỉ API có thể đổi qua biến `ZALO_API_BASE`).
