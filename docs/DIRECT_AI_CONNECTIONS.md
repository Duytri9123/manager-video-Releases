# Kết nối AI trực tiếp (không cần chạy 9Router)

Tool chỉ dùng kiến thức giao thức/provider lấy từ mã nguồn 9Router. Mọi request chạy
trực tiếp từ tool tới upstream; không gọi `localhost:20128`, `/v1` của 9Router hay
DTRouter ở cổng `9123`.

## Antigravity / Google OAuth

1. Chạy tool và mở **Nhà cung cấp → Antigravity → Thêm kết nối**.
2. Bấm **Đăng nhập Google**.
3. Đăng nhập và chấp thuận trong cửa sổ Google. Google trả callback về route
   `/callback` của chính tool đang chạy.
4. Tool tự đổi authorization code lấy access/refresh token, lấy Cloud Code Assist
   project ID và lưu kết nối vào `.state/providers.db`.
5. Bấm **Test** trên một model. Lúc này request được gửi thẳng tới
   `daily-cloudcode-pa.googleapis.com`; access token được tự làm mới khi gần hết hạn.

Callback loopback ở đây thuộc toolvideo và chỉ dùng để hoàn tất OAuth trong trình
duyệt. Nó không phải endpoint proxy của 9Router.

## Google AI Studio API key

Thêm kết nối Antigravity bằng key bắt đầu với `AIza...` và giữ Base URL là
`https://generativelanguage.googleapis.com`. Tool gọi trực tiếp Gemini
`v1beta/models/...:generateContent`.

## Provider tương thích OpenAI

Với OpenAI, DeepSeek, Groq, OpenRouter, NVIDIA hoặc endpoint tùy chỉnh, nhập API key
và Base URL upstream thật. Chức năng test model tự chuẩn hóa Base URL thành
`/v1/chat/completions` và gọi trực tiếp bằng Bearer token.

## Dữ liệu được lưu

Bảng `provider_connections` lưu loại xác thực, access token, refresh token, thời
điểm hết hạn, project ID và email. Không cần đọc database hoặc tiến trình của
9Router. Không đưa file `.state/providers.db` lên Git hoặc chia sẻ cho người khác.
