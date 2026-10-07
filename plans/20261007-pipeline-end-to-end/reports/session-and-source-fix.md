# Sửa phiên mới và lượt crawl Hà Nam

2026-10-07, Asia/Ho_Chi_Minh.

## Nguyên nhân tái hiện

- Phiên `2d96fce489c841fd9da0036f3850a133` (`ha-nam`): không có URL đầu vào, ba truy vấn DuckDuckGo đều HTTP 202. Chưa đến bước tải bài nguồn. Đây không phải lỗi key embedding.
- UI cũ render toàn bộ job liên tiếp và luôn điền mặc định Bình Phước; không có nút dọn biểu mẫu. Lịch sử trộn với phiên đang làm gây hiểu nhầm dữ liệu còn cũ.
- Retry bằng URL Nhân Dân (`e49a4d4c5d15486da61a6224b19150ee`) phát hiện `Compressed source response is not supported` khi tải robots.txt. Probe thật: HTTP 200, `Content-Encoding: gzip`, dù request `Accept-Encoding: identity`.

## Thay đổi

- **＋ Tạo phiên mới** dọn scope/collection/URL, chọn URL trực tiếp, đặt 3 trang/độ sâu 0/BTC. Chỉ trạng thái biểu mẫu thay đổi; dữ liệu và key không bị xóa.
- Chỉ một thẻ **Phiên đang xem**. Các job khác trong **Lịch sử** thu gọn với nút mở. Lưu ID/lựa chọn trống theo tab, không lưu key hay tài liệu trong trạng thái này.
- Chế độ URL trực tiếp yêu cầu URL khi crawl; build không bắt buộc URL. Tự tìm DuckDuckGo là lựa chọn rõ ràng, có cảnh báo HTTP 202.
- Trace chẩn đoán tìm nguồn HTTP 202 chỉ khi tất cả search node thất bại, issue liên kết đúng host DuckDuckGo và không có seed/doc. Không áp dụng nhầm cho lỗi URL trực tiếp, HTTP khác hoặc đang chạy.
- Bộ tải dùng giải nén gzip chuẩn, kiểm CRC/thiếu dữ liệu và giới hạn cả dữ liệu nén/sau giải nén. Cùng helper cho nhập URL và crawler. Giữ kiểm DNS/IP public, HTTPS, robots và redirect.

## Chạy thật thành công

- Nguồn: [Hà Nam tăng trưởng kinh tế-xã hội đứng thứ 2 vùng Đồng bằng sông Hồng](https://nhandan.vn/ha-nam-tang-truong-kinh-te-xa-hoi-dung-thu-2-vung-dong-bang-song-hong-post848488.html), Nhân Dân, ngày bài 04/12/2024.
- Giữ scope người dùng: kinh tế, văn hóa Hà Nam 2020–2024; collection `ha-nam`; URL trực tiếp, 1 trang, depth 0.
- Phiên `caab84ff992447a2b1fc529ae7df6ecc` lúc 15:21:04 giờ Việt Nam: `needs_review`, 1 nguồn/1 URL/1 tài liệu chờ, 0 URL lỗi.
- Document `cb0ea0e120b3464f90464241206ae9d0`: `pending`, 3.428 ký tự (có cấu trúc bảng/chú thích ảnh cần người đối chiếu), 6 đoạn preview. Điểm trích xuất 100 không phải confidence sự thật.
- Chưa phê duyệt; API export `ha-nam` vẫn rỗng, xác nhận gate duyệt. Không gọi embedding hoặc đổi key trong lượt sửa này.

## Kiểm chứng

- UI thật: Tạo phiên mới dọn toàn bộ trường cũ, reload vẫn trống, chỉ thẻ phiên mới sau submit. Lịch sử mở chọn đúng phiên lỗi cũ rồi trở lại phiên thành công. **Tiếp tục duyệt 1 tài liệu →** mở đúng document Hà Nam ở pending.
- 5 test trace qua, gồm điều kiện chẩn đoán và các trường hợp không được chẩn đoán nhầm.
- 27 test tập trung + 10 subtests qua sau sửa gzip; kiểm dữ liệu nén thật, boundary size, nhiều gzip member, CRC sai, thiếu dữ liệu và encoding lạ.
- Toàn ứng dụng: **63 passed, 30 subtests passed**; Ruff check/format và Node syntax đều qua. Một cảnh báo deprecation TestClient/httpx từ dependency, không có test lỗi.
- Reviewer độc lập không còn finding cho session/history/trace và gzip; không sửa checkout upstream.
- Tự tìm nguồn vẫn phụ thuộc DuckDuckGo, chưa được coi là đã sửa dịch vụ bên ngoài. Một bài Hà Nam không thay thế thu thập đầy đủ toàn giai đoạn.
