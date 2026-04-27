# Ticket: Freshness Center MVP

## Mục tiêu
Xây nền cho một **Freshness Center** trong admin để theo dõi độ tươi của knowledge base sources và hỗ trợ re-crawl có chọn lọc. Mục tiêu của MVP là cải thiện độ tin cậy câu trả lời bằng cách giúp admin biết nguồn nào stale/dead và kích hoạt ingest lại nhanh hơn.

## Bối cảnh hiện tại
Repo đã có:
- logic kiểm tra source trong `tools/check_sources.py`
- admin endpoints liên quan health check / ingest trong `api/admin.py`
- nguyên tắc không cho reset KB qua HTTP

Nhưng hiện vẫn thiếu:
- snapshot lưu trạng thái freshness theo thời gian
- khả năng nhìn lại `last_checked_at`, `last_status`
- API batch re-crawl selected URLs từ các nguồn stale/dead
- nền dữ liệu để sau này dựng UI admin Freshness

## Phạm vi MVP
### Backend/API only, ưu tiên nền dữ liệu trước
Làm các phần sau:

1. **Persistence cho freshness snapshot**
   - Tạo nơi lưu trạng thái freshness của source (SQLite hoặc file local có cấu trúc rõ ràng; ưu tiên đồng bộ với style hiện có của repo)
   - Mỗi record nên có tối thiểu:
     - `url`
     - `topic` (nếu có)
     - `status` (`OK`, `STALE`, `DEAD`, `REDIRECT`, `ERROR`)
     - `checked_at`
     - `http_status` (nếu có)
     - `notes` hoặc `error_message` (nếu có)

2. **Snapshot/update flow**
   - Khi chạy health check nguồn, kết quả cần được lưu lại thay vì chỉ trả realtime
   - Có endpoint/API nội bộ hoặc logic service để refresh snapshot từ source check hiện tại

3. **Read API cho admin**
   - Bổ sung endpoint để lấy danh sách freshness records
   - Hỗ trợ filter cơ bản theo:
     - `status`
     - `topic` (nếu có)
   - Sắp xếp mặc định theo `checked_at` mới nhất hoặc ưu tiên lỗi/stale lên trước

4. **Batch re-crawl selected URLs**
   - Thêm endpoint admin cho phép truyền danh sách URL cần re-crawl
   - Endpoint này phải tận dụng flow ingest hiện có nếu phù hợp
   - Chỉ re-crawl các URL được chọn, không reset toàn KB
   - Giữ nguyên nguyên tắc an toàn: **không thêm reset KB qua HTTP**

5. **Minimal observability/logging**
   - Log số lượng URL được check
   - Log số lượng stale/dead/error
   - Log batch re-crawl action

## Không nằm trong ticket này
- Chưa cần làm UI Streamlit/admin hoàn chỉnh
- Chưa cần scheduler định kỳ
- Chưa cần alerting
- Chưa cần auth/RBAC overhaul ngoài phần tối thiểu đang có
- Chưa cần redesign toàn bộ ingest pipeline thành background jobs

## Kết quả mong muốn
Sau ticket này, repo phải có khả năng:
1. Chạy check freshness và lưu snapshot
2. Query được snapshot đã lưu
3. Gọi batch re-crawl cho một nhóm URLs stale/dead
4. Dùng được làm nền cho UI Freshness Center ở bước sau

## Gợi ý triển khai
- Ưu tiên tái sử dụng code hiện có trong:
  - `tools/check_sources.py`
  - `api/admin.py`
  - bất kỳ storage pattern nào repo đang dùng cho SQLite/local persistence
- Tránh tạo kiến trúc quá to cho MVP
- Nên giữ code dễ test

## Acceptance criteria
- Có persistence cho freshness snapshot
- Có API đọc freshness records
- Có API batch re-crawl selected URLs
- Có test cho luồng chính:
  - lưu snapshot
  - đọc snapshot
  - batch re-crawl selected URLs
- Test hiện có không bị vỡ
- Không làm lộ `.env`, secrets, hoặc mở lại reset KB qua HTTP

## Ưu tiên thực hiện
1. Model/persistence + service
2. Admin API read/list
3. Admin API batch re-crawl
4. Tests
5. Docs ngắn nếu cần

## Định nghĩa xong việc
- Code chạy qua test
- Không phá behavior admin hiện tại
- Có thể demo backend bằng cách:
  - check freshness
  - thấy dữ liệu snapshot
  - chọn một nhóm URLs để re-crawl
