# HƯỚNG DẪN BUILD ỨNG DỤNG DUYTRIS DOWNLOADER

Tài liệu này tổng hợp toàn bộ quy trình và các câu lệnh đã thực hiện để build ứng dụng từ mã nguồn Python ra file thực thi `.exe` và đóng gói bộ cài đặt `Setup.exe`.

---

## 1. Các bước chuẩn bị trước khi build

### 1.1. Cài đặt các thư viện cần thiết
Đảm bảo bạn đã kích hoạt môi trường ảo `.venv` và cài đặt đầy đủ dependencies:
```powershell
# Kích hoạt môi trường ảo (PowerShell)
.venv\Scripts\Activate.ps1

# Cài đặt các thư viện từ requirements.txt nếu có thay đổi
pip install -r requirements.txt
```

### 1.2. Tạo ảnh Bitmap cho giao diện cài đặt (Inno Setup)
Inno Setup yêu cầu ảnh logo định dạng `.bmp` với kích thước chuẩn để tránh bị lỗi hiển thị khi mở bộ cài. Câu lệnh Python sau đã được chạy để tự động tạo 2 file ảnh này từ logo gốc `img/dowload_logo.png`:
```powershell
python -c "
from PIL import Image
import os

src = r'img/dowload_logo.png'
img_dir = r'installer'
img = Image.open(src).convert('RGB')

# Ảnh lớn bên trái wizard (164x314 pixels)
wizard_large = img.resize((164, 314), Image.LANCZOS)
wizard_large.save(os.path.join(img_dir, 'wizard_image.bmp'), 'BMP')
print('Tạo wizard_image.bmp thành công!')

# Ảnh nhỏ góc trên bên phải wizard (55x58 pixels)
wizard_small = img.resize((55, 58), Image.LANCZOS)
wizard_small.save(os.path.join(img_dir, 'wizard_small.bmp'), 'BMP')
print('Tạo wizard_small.bmp thành công!')
"
```

---

## 2. Quy trình Build ứng dụng

Quy trình build hoàn chỉnh gồm 2 bước chính dưới đây:

### Bước 1: Biên dịch mã nguồn Python ra file thực thi (.exe)
Chạy script `build_exe.ps1` ở thư mục gốc của dự án. Script này sẽ tự động:
1. Xóa các thư mục build cũ để dọn dẹp dung lượng.
2. Chạy **PyArmor** để mã hóa bảo mật các module quan trọng trong `obf_src/`.
3. Chạy **PyInstaller** để đóng gói toàn bộ thư viện (PySide6, ONNX, ctranslate2, v.v.) vào thư mục phân phối `dist/DuyTrisDownloader`.
4. Copy các file thực thi của **FFmpeg** (`ffmpeg.exe`, `ffprobe.exe`) từ thư mục `cli/` vào gói build.
5. Tạo file nén Portable dạng `.zip` để phân phối nhanh.

**Lệnh thực hiện:**
```powershell
powershell.exe -File .\build_exe.ps1
```

### Bước 2: Đóng gói bộ cài đặt Setup (Inno Setup)
Sau khi Bước 1 chạy thành công và tạo ra file `.exe` cùng các tài nguyên trong thư mục `dist/`, chạy script đóng gói dưới đây để tạo ra file Setup duy nhất. Script này sẽ gọi trình biên dịch `ISCC.exe` của Inno Setup 6 trên máy của bạn để tạo ra bộ cài.

**Lệnh thực hiện:**
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\installer\Build-Installer.ps1 -OutputExe .\output\DuyTrisDownloader_Setup.exe
```

---

## 3. Kết quả đầu ra (Output)

Sau khi hoàn thành 2 bước trên, các file phân phối sẽ nằm tại:

| File đầu ra | Đường dẫn | Công dụng |
|:---|:---|:---|
| **Bộ cài đặt Setup** | `output\DuyTrisDownloader_Setup.exe` | Bộ cài đặt Windows chính thức cho người dùng cuối (đã tích hợp Icon và Logo). |
| **Bản chạy ngay (Portable)** | `dist\DuyTrisDownloader_Portable.zip` | Gói nén chạy ngay không cần cài đặt. |
| **Thư mục chạy thử** | `dist\DuyTrisDownloader\` | Thư mục giải nén thô để test nhanh ứng dụng trước khi nén. |

---

## 4. Cấu hình Backend trên Production Server (Lưu ý quan trọng)

Để ứng dụng kết nối và kích hoạt Key/Dùng thử được bình thường, bạn cần:
1. Upload file `app/Http/Middleware/HmacMiddleware.php` đã sửa đổi lên host của bạn.
2. Thêm dòng cấu hình khóa HMAC vào file `.env` trên host:
   ```env
   HMAC_SECRET_KEY="DuYtRiS_s3cr3t_k3y_2024!@#"
   ```
