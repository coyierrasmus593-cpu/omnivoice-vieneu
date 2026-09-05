# HANDOVER — OmniVoice Build (Portable + Security)

## Ngày cập nhật: 2026-04-12
## Trạng thái: ĐÃ XÁC ĐỊNH ROOT CAUSE, ĐÃ PATCH, CẦN AI TIẾP THEO CHẠY VERIFY FULL BUILD

---

## 1) Mục tiêu bàn giao
Hoàn tất build phát hành portable cho khách với:
- bảo mật (main_secure + anti-debug + integrity + runtime guard + license)
- model OmniVoice bundle sẵn trong dist
- artifacts phát hành (sha256 + manifest)
- smoke-test pass (`SMOKE_TEST_OK`)

---

## 2) Trạng thái hiện tại (thực tế mới nhất)

### 2.1 Build script
`D:/02.Code/Omni1-build/build_omnivoice.py` đã hoàn thiện pipeline chính (PyArmor + PyInstaller + hash + release artifact + smoke test).

### 2.2 Workspace dùng để build
Do E: từng lỗi I/O/Invalid argument khi build lớn, luồng build đang chạy trên:
- `D:/02.Code/Omni1-build`

### 2.3 Chiến lược PyArmor trial (theo yêu cầu user)
Chỉ obfuscate file quan trọng bảo mật/logic:
- `main_secure.py`
- `src/core/license_client.py`
- `src/core/runtime_guard.py`
- `src/core/_internal_hashes.py`

### 2.4 Triệu chứng đang xử lý
Build ra exe thành công, nhưng smoke test trước đó fail:
- `OmniVoiceCloner.exe --smoke-test` -> exit code `1`

---

## 3) Root cause đã xác định (quan trọng)

### 3.1 Bằng chứng điều tra
1. Chạy script obfuscated trực tiếp (không frozen) pass:
   - `python main_secure.py --smoke-test` -> `SMOKE_TEST_OK`
2. Chạy exe frozen fail:
   - `dist/OmniVoiceCloner/OmniVoiceCloner.exe --smoke-test` -> exit `1`
3. Extract PYZ cho thấy module obfuscated import runtime theo kiểu:
   - `from pyarmor_runtime_000000 import __pyarmor__`
4. Trong bundle `_internal/pyarmor_runtime_000000/` chỉ có `pyarmor_runtime.pyd`, thiếu `__init__.py`.
5. Khi thiếu `__init__.py`, `pyarmor_runtime_000000` thành namespace package, không export `__pyarmor__`, làm import fail rất sớm -> exe thoát mã 1.

### 3.2 Kết luận
Root cause là **missing `__init__.py` trong runtime package `pyarmor_runtime_000000` được copy vào project trước PyInstaller**.

---

## 4) Patch đã áp dụng

Đã sửa trong `D:/02.Code/Omni1-build/build_omnivoice.py` (hàm `run_pyarmor_obfuscation`):
- sau `shutil.copytree(runtime_src, runtime_dst)`
- nếu thiếu `runtime_dst/__init__.py` thì tự tạo:

```python
runtime_init = runtime_dst / "__init__.py"
if not runtime_init.exists():
    runtime_init.write_text("from .pyarmor_runtime import __pyarmor__\n", encoding="utf-8")
```

Vị trí hiện tại trong file: khoảng dòng 372-375.

---

## 5) Việc còn lại cho AI tiếp theo (ưu tiên theo thứ tự)

### Bước 1 — chạy lại full build để verify patch
```bash
python D:/02.Code/Omni1-build/build_omnivoice.py
```

### Bước 2 — xác nhận smoke-test pass trong log build
Cần thấy:
- `[RUN] ...OmniVoiceCloner.exe --smoke-test`
- `SMOKE_TEST_OK`
- `[OK] Smoke test passed`
- `[OK] Build completed successfully`

### Bước 3 — xác nhận artifacts phát hành
Phải tồn tại:
- `D:/02.Code/Omni1-build/dist/OmniVoiceCloner/OmniVoiceCloner.exe`
- `D:/02.Code/Omni1-build/dist/OmniVoiceCloner.exe.sha256`
- `D:/02.Code/Omni1-build/dist/RELEASE_MANIFEST.json`

### Bước 4 — sanity check runtime package sau build
Xác nhận có file:
- `D:/02.Code/Omni1-build/dist/OmniVoiceCloner/_internal/pyarmor_runtime_000000/__init__.py`

---

## 6) Nếu build vẫn fail
1. Lấy stdout/stderr đoạn cuối build + smoke-test.
2. Chạy tay:
   ```bash
   D:/02.Code/Omni1-build/dist/OmniVoiceCloner/OmniVoiceCloner.exe --smoke-test
   ```
3. Nếu vẫn exit 1, kiểm tra tiếp import runtime package trong `_internal` (khả năng cao liên quan runtime packaging).
4. Không mở rộng obfuscation sang file ngoài phạm vi trial/security-critical nếu chưa có yêu cầu mới.

---

## 7) Ghi chú vận hành
- Một số thao tác đọc/grep trực tiếp vào `dist/` hoặc `build/` từ context `E:/Omni1` có thể bị hook chặn; dùng command Python trực tiếp theo absolute path ở `D:/02.Code/Omni1-build` để kiểm tra.
- Build rất nặng (torch + model), nên ưu tiên đọc log incremental thay vì chạy lại nhiều lần không cần thiết.

---

## 8) Snapshot lệnh gần nhất
Đã khởi chạy full build sau patch nhưng dừng giữa chừng để cập nhật handover theo yêu cầu user.
AI tiếp theo cần chạy lại full build sạch theo Bước 1 để có kết quả xác thực cuối cùng.
