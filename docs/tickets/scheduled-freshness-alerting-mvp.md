# Ticket: Scheduled Freshness Checks + Alerting MVP

## Mục tiêu
Biến Freshness Center từ công cụ chạy tay thành một vòng kiểm tra tự động, để knowledge base sources được kiểm tra định kỳ và admin được cảnh báo sớm khi có nguồn lỗi, stale, dead hoặc redirect bất thường.

## Vì sao cần làm tiếp ngay sau Freshness Center
Hiện tại repo đã có:
- freshness snapshot persistence
- admin API xem freshness records
- batch recrawl selected URLs
- UI Freshness Center để xem và thao tác thủ công

Khoảng trống còn lại:
- health-check vẫn chạy tay
- không có lịch chạy định kỳ
- không có khái niệm last run / next run
- không có alerting khi nguồn bắt đầu hỏng

Điều này làm Freshness Center mới chỉ là công cụ kiểm tra khi nhớ đến, chưa phải hệ thống giữ KB luôn đáng tin cậy.

## Nguyên tắc MVP
### 1. Reliability trước, fancy sau
- Ưu tiên chạy ổn định, dễ hiểu, dễ debug
- Không thêm scheduler UI phức tạp kiểu calendar builder
- Không thêm notification center nặng nề

### 2. Scope nhỏ nhưng dùng được hằng ngày
- Chỉ cần một scheduler đơn giản cho toàn hệ thống
- Chỉ cần một vài rule alert cơ bản
- Chỉ cần admin nhìn được trạng thái scheduler và lần chạy gần nhất

### 3. Bám kiến trúc hiện có
- Tận dụng `run_health_check` / freshness persistence đã có
- Không tạo business logic trùng lặp ở UI
- Không redesign Freshness Center hiện tại

## Phạm vi MVP

### A. Scheduler backend tối thiểu
Thêm một cơ chế chạy health-check định kỳ ở backend.

Yêu cầu tối thiểu:
- bật / tắt scheduler
- cấu hình chu kỳ chạy đơn giản, ví dụ mỗi N phút hoặc một interval rõ ràng
- khi đến lịch, tự gọi flow health-check hiện có cho toàn bộ sources
- persist freshness snapshot như flow manual hiện tại

Không cần ở MVP:
- cron expression editor đầy đủ
- multi-job scheduler
- per-topic schedules riêng

### B. Scheduler status / run history tối thiểu
Cần có dữ liệu để admin biết scheduler có đang sống không.

Hiển thị / lưu tối thiểu:
- scheduler enabled hay disabled
- interval hiện tại
- last run time
- next run time
- last run result summary:
  - total
  - ok
  - stale
  - dead
  - redirect
  - error/unknown
  - snapshot_saved
  - duration nếu tiện
- nếu run fail hoàn toàn thì lưu lỗi ngắn gọn để admin thấy

Không cần ở MVP:
- lịch sử dài nhiều ngày
- analytics sâu
- charts

### C. Alerting MVP
Cần có cảnh báo tối thiểu khi health-check phát hiện vấn đề.

MVP đề xuất:
- alert condition cơ bản:
  - có `DEAD`
  - có `ERROR`
  - hoặc số `STALE` vượt ngưỡng đơn giản
- alert output tối thiểu theo thứ tự ưu tiên:
  1. ghi summary rõ vào backend log
  2. hiển thị banner / trạng thái cảnh báo trong admin UI
  3. nếu repo đã có sẵn đường gửi message thuận tiện thì cân nhắc một kênh notify duy nhất, nhưng chỉ nếu scope vẫn gọn

Không cần ở MVP:
- notification rule builder
- multi-channel routing phức tạp
- dedupe/ack workflow đầy đủ

### D. Admin UI tối thiểu
Mở rộng Freshness Center hoặc Admin để có một vùng “Scheduler / Alerts” rất gọn.

Cần có:
- nút bật / tắt scheduler
- chọn interval đơn giản
- hiển thị last run / next run
- hiển thị summary lần chạy gần nhất
- hiển thị alert state hiện tại
- vẫn giữ UI tối giản, text-first, không dashboard màu mè

Không cần ở MVP:
- biểu đồ theo thời gian
- timeline phức tạp
- nhiều widget nhỏ khó đọc

## Acceptance criteria
- có thể bật scheduler để hệ thống tự chạy health-check định kỳ
- run định kỳ dùng lại flow freshness hiện có và persist dữ liệu đúng
- admin thấy được scheduler status: enabled, interval, last run, next run
- khi có vấn đề (`DEAD` / `ERROR` / stale vượt ngưỡng), hệ thống tạo alert summary rõ ràng
- admin nhìn được alert state hiện tại trong UI
- toàn bộ feature vẫn tối giản, dễ debug, không thêm quá nhiều moving parts

## Câu hỏi thiết kế cần chốt trước khi code
1. scheduler nên chạy trong process FastAPI hiện tại hay một worker/background loop riêng?
2. state scheduler / last run nên lưu ở đâu để restart không mất?
3. alert MVP chỉ dừng ở UI + log, hay có gửi ra Telegram luôn?
4. interval mặc định hợp lý là bao lâu?
5. stale threshold mặc định nên là gì?

## Scope chốt để implement ngay
Chốt MVP theo hướng nhỏ nhất nhưng usable:

1. **Backend scheduler trong process hiện tại**
   - dùng một background loop / scheduler tối giản trong backend hiện tại
   - không tách worker riêng ở MVP
   - interval dạng đơn giản: mỗi N phút

2. **Persisted scheduler state**
   - lưu trạng thái scheduler + last run summary vào storage local bền vững
   - restart app không mất hoàn toàn trạng thái gần nhất

3. **Admin API tối thiểu**
   - read scheduler status
   - update enable/disable + interval
   - trả last run / next run / last summary

4. **UI admin tối giản**
   - trong Freshness Center hoặc Admin có vùng Scheduler/Alerts rất gọn
   - chỉ gồm: enable/disable, interval, last run, next run, last summary, alert state

5. **Alert MVP chỉ ở UI + log**
   - chưa gửi Telegram ở pha này
   - chỉ cần alert summary rõ ràng trong log và admin UI

## Scope cắt bỏ ở vòng này
- không Telegram notify
- không per-topic schedules
- không cron expression editor
- không multi-job scheduler
- không long history view
- không charts/timeline
- không notification center
- không rule builder

## Thứ tự implement khuyến nghị
1. scheduler state persistence
2. background scheduler loop gắn với health-check hiện có
3. admin read/write API cho scheduler
4. UI scheduler/alert section tối giản
5. tests cho scheduler state + API

## Không nằm trong ticket này
- cron builder đầy đủ
- per-topic schedules
- charts/timeline/history explorer
- rule engine cho alerts
- escalation workflow
- auth/rbac mới
- redesign toàn bộ admin
- mobile-first UI riêng

## Định nghĩa xong việc
Có thể demo theo flow:
1. admin bật scheduler
2. hệ thống tự chạy health-check định kỳ
3. freshness records tiếp tục được cập nhật tự động
4. admin mở UI thấy last run / next run / trạng thái cảnh báo
5. khi có nguồn lỗi, admin thấy cảnh báo đủ rõ để quyết định recrawl hoặc xử lý tiếp
