1. xml:space="preserve" trong <templates xml:space="preserve"> là gì ?
- Thuộc tính này bảo XML/QWeb rằng khoảng trắng, xuống dòng, và khoảng cách trong vùng đó nên được bảo toàn thay vì bị chuẩn hóa tự động. 
- Trong thực tế Odoo/OWL, nó xuất hiện gần như mặc định trong file template để tránh việc format XML làm thay đổi nội dung hiển thị ngoài ý muốn.
2. t-esc và t-out 
- t-esc → escape an toàn, dùng cho text thường
- t-out + markup() → render HTML, chỉ dùng với nội dung tin cậy, chống xss (Tự động escape nội dung trừ khi được đánh dấu rõ ràng là an toàn bằng hàm markup())