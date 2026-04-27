# Ticket: Freshness Center UI MVP

## Mục tiêu
Dựng giao diện admin tối giản cho **Freshness Center** dựa trên backend/API đã có, để admin có thể xem nhanh tình trạng freshness của knowledge base sources và kích hoạt re-crawl có chọn lọc mà không cần gọi API thủ công.

## Bối cảnh hiện tại
Backend MVP đã có nền tảng:
- lưu freshness snapshot
- API đọc freshness records
- API batch re-crawl selected URLs
- health-check có persist snapshot

Việc còn thiếu là một UI admin đủ gọn để sử dụng hằng ngày.

## Nguyên tắc thiết kế bắt buộc
### 1. Tối giản và chuyên nghiệp
- Ưu tiên giao diện sạch, rõ, dễ đọc
- **Hạn chế icon ở mức tối đa**
- Không tự ý thêm icon trang trí, emoji, biểu tượng vui vẻ, badge màu mè nếu không thật sự cần
- Chỉ dùng icon nếu nó phục vụ chức năng rõ ràng và không có phương án text tốt hơn
- Tránh cảm giác “dashboard màu mè”; ưu tiên phong cách admin tool nghiêm túc

### 2. Không tự mở rộng scope UI
- Không tự ý thêm animation, charts, widgets, cards rườm rà
- Không thêm các thành phần ngoài scope nếu chưa có yêu cầu rõ
- Không redesign toàn bộ admin hiện tại

### 3. Backend-first integration
- UI phải bám đúng API hiện có
- Không tự chế business logic lớn ở UI nếu backend đã cung cấp rồi

## Phạm vi MVP
Làm các phần sau:

1. **Trang / section Freshness Center trong admin UI**
   - Hiển thị danh sách freshness records từ API
   - Có các cột tối thiểu:
     - URL
     - topic
     - status
     - checked_at
     - http_status
     - notes / error_message

2. **Filter cơ bản**
   - Filter theo `status`
   - Filter theo `topic`
   - Có nút refresh/load lại dữ liệu

3. **Run health-check từ UI**
   - Cho phép chạy health-check cho toàn bộ hoặc theo topic (tuỳ backend hiện hỗ trợ thế nào)
   - Sau khi chạy xong, UI cập nhật lại danh sách

4. **Batch recrawl selected URLs**
   - Cho phép chọn 1 hoặc nhiều rows
   - Có action re-crawl cho các URL đã chọn
   - Hiển thị kết quả action ngắn gọn, rõ ràng

5. **Trình bày status rõ ràng nhưng tiết chế**
   - Có thể dùng text hoặc màu nhẹ để phân biệt `OK`, `STALE`, `DEAD`, `ERROR`, `REDIRECT`
   - Không lạm dụng icon/emoji cho status

## Không nằm trong ticket này
- Không thêm charts/graphs
- Không thêm timeline/history view sâu
- Không thêm scheduler UI
- Không thêm notifications/alert center
- Không thêm auth/RBAC mới
- Không redesign toàn bộ navigation nếu không cần

## Yêu cầu UX/UI chi tiết
- Ưu tiên table rõ ràng, spacing gọn, dễ scan
- Text labels ưu tiên hơn icon buttons mơ hồ
- Nếu có action button, label phải rõ nghĩa
- Tránh quá nhiều màu; chỉ dùng màu như tín hiệu phụ trợ
- Tránh icon-only controls nếu có thể dùng text
- Nếu cần xác nhận action re-crawl, dùng xác nhận ngắn gọn và chuyên nghiệp

## Acceptance criteria
- Có UI hiển thị freshness records từ API
- Có filter status/topic
- Có thể trigger health-check từ UI
- Có thể chọn nhiều URL và trigger batch recrawl
- UI hoạt động với backend hiện tại mà không cần hack logic vòng ngoài
- Giao diện giữ phong cách tối giản, chuyên nghiệp
- **Không tự ý thêm icon dư thừa hoặc các yếu tố trang trí không cần thiết**

## Định nghĩa xong việc
- Có thể demo bằng UI theo flow:
  1. mở Freshness Center
  2. xem danh sách freshness
  3. filter theo status/topic
  4. chạy health-check
  5. chọn một số URL và re-crawl
- UI đủ sạch để dùng nội bộ mà không có cảm giác rối hoặc màu mè
