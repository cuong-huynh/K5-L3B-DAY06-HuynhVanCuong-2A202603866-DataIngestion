# Báo cáo cá nhân — Day 6

Huỳnh Văn Cường · 2A202603866 · L3B

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:** ba luật Việt Nam về không gian số, lấy nguyên bản PDF từ Công báo Chính phủ: Luật An ninh mạng 116/2025/QH15 (37 trang), Luật Giao dịch điện tử 20/2023/QH15 (30 trang), Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 (25 trang). Tổng **92/92 trang nội dung**. Văn bản quy phạm pháp luật không thuộc đối tượng bảo hộ quyền tác giả (Điều 15 Luật Sở hữu trí tuệ). Quy tắc tính: trang vật lý của PDF, đánh số từ 1; một trang được tính nếu sau chuẩn hóa còn ít nhất 200 ký tự văn bản luật. Mỗi file chỉ chứa đúng một luật, không có bìa hay mục lục. URL, SHA-256, ngày truy cập và số ký tự từng trang nằm trong [`data/manifest.json`](../../data/manifest.json).
- **Chuẩn hóa, lỗi và giới hạn:**
  - Bản PDF trên vanban.chinhphu.vn của Luật An ninh mạng và Luật Bảo vệ dữ liệu cá nhân là **bản scan, không có lớp chữ** (0 ký tự trên mọi trang). Tôi thay bằng bản Công báo có lớp chữ thay vì chạy OCR.
  - `pypdf` tách sai dấu tiếng Việt ("đe d ọa", "Chứng th ư"), nên tôi dùng PyMuPDF.
  - Các bước chuẩn hóa: Unicode NFC; bỏ dòng tiêu đề "CÔNG BÁO/Số…", số trang Công báo và các dạng dấu chữ ký số; nối dòng bị ngắt thành đoạn. Dòng in đậm được coi là tiêu đề (Chương, Mục, Điều). Số Chương và Điều được mang sang trang sau và đặt lại khi gặp Chương hoặc Mục mới.
  - Kết quả: 0 trang lỗi ([`results/ingestion_errors.json`](../../results/ingestion_errors.json)).
  - Giới hạn: chunk không vượt qua ranh giới trang, nên khoản kéo dài sang trang sau bị tách đôi (xem ví dụ q17).
- **Embedding, vector store, lệnh chạy và chi phí:**
  - Embedding: `intfloat/multilingual-e5-small` chạy local trên CPU qua sentence-transformers 6.3.0 (torch 2.15.0, transformers 5.23.0). Vector 384 chiều, chuẩn hóa L2. Tài liệu được thêm tiền tố `passage: `, câu hỏi thêm tiền tố `query: `, đúng theo hướng dẫn của model. Model nhận tối đa 512 token và 0 chunk bị cắt cụt.
  - Vector store: PostgreSQL 16.16 + pgvector 0.8.7 chạy trong Docker. Bảng `law_chunks`, khóa chính `(strategy, chunk_id)`. Tìm kiếm cosine chính xác, không dùng chỉ mục xấp xỉ (ANN).
  - Lệnh chạy: `python -m src.manifest` rồi `python -m src.run`, chạy trong thư mục `starter/`.
  - Chi phí 0 USD. Toàn bộ pipeline chạy khoảng 23 giây. Thời gian tạo embedding khoảng 3,6–3,9 giây mỗi cấu hình ([`results/run_log.json`](../../results/run_log.json)).
- **Metadata bắt buộc, trường lọc và lý do chọn:**
  - Trường bắt buộc: `document_id`, `source` (đường dẫn PDF), `page` (trang PDF).
  - Trường bổ sung: `gazette_page`, `law_title`, `law_number`, `year` và `effective_date` (trích bằng regex từ câu "thông qua ngày…" và "có hiệu lực thi hành từ ngày…", không tự điền), `chapter`, `article`, `article_title`, `articles`.
  - Trường lọc: `document_id`, được lưu thành cột SQL và lọc trước khi xếp hạng. Lý do chọn: Điều 1 (phạm vi điều chỉnh), Điều 2 (đối tượng áp dụng) và Điều về hiệu lực thi hành của ba luật có câu chữ gần như giống nhau, nên một câu hỏi chung không phân biệt được luật nào.

## Cấu hình và benchmark

- **A / B / C:**
  - **A:** cửa sổ 1.000 ký tự, chồng lấn 150 ký tự, trong phạm vi từng trang, không lọc.
  - **B:** bắt đầu chunk mới ở mỗi tiêu đề Chương, Mục hoặc Điều; gom các khoản và điểm tới tối đa 1.000 ký tự; đoạn quá dài cắt theo câu; không lọc.
  - **C:** dùng cùng chunk với B, có thêm `WHERE document_id = …`, chỉ áp dụng cho câu hỏi có filter.
  - A–B chỉ khác cách chọn ranh giới chunk (cùng giới hạn 1.000 ký tự, cùng model và metadata). B–C chỉ khác việc lọc.
- **Bộ câu hỏi:** 20 câu trong [`benchmark/questions.jsonl`](../../benchmark/questions.jsonl), chia **15 dev / 5 test**.
  - Có câu hỏi trực tiếp, câu diễn đạt lại, câu có điều kiện hoặc ngoại lệ, và 4 câu kiểm tra filter: q14, q15 thuộc dev; q16, q20 thuộc test.
  - Filter là phạm vi văn bản mà người dùng chọn trước khi hỏi (giả định giao diện có ô chọn luật). Câu hỏi được viết chung chung, không nêu tên luật.
  - Hàm `verify_benchmark` kiểm tra mỗi đoạn bằng chứng nằm nguyên văn trên đúng trang gold sau chuẩn hóa: 20/20 đạt. Pipeline dừng nếu có câu không đạt.
  - Bộ câu hỏi và cách chia được commit ở `b47a02d` **trước** lần chạy đầu tiên.
- **Tiêu chí chọn chiến lược:**
  - Tiêu chí: ưu tiên Evidence Hit@3 trên dev, sau đó Hit@1 trên dev, sau đó coherence, cuối cùng là tài nguyên.
  - Không có tham số nào bị chỉnh sau khi chạy.
  - Lưu ý trung thực: script in kết quả dev và test trong cùng một lần chạy, nên tôi không có bằng chứng thời gian cho thấy tiêu chí được chốt trước khi số liệu test hiện ra. Dù vậy, áp tiêu chí này chỉ trên dev đã chọn được C (Hit@3 15/15, Hit@1 14/15).

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian embed | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 11/15 | 14/15 | 258 | 3.92 s | 0 |
| A | test | 2/5 | 2/5 | 258 | | 0 |
| B | dev | 12/15 | 15/15 | 320 | 3.64 s | 0 |
| B | test | 1/5 | 3/5 | 320 | | 0 |
| C | dev | 14/15 | 15/15 | 320 | 3.66 s | 0 |
| C | test | 3/5 | 4/5 | 320 | | 0 |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0.8 (10) | 14/15 | 0/2 test (không áp filter) | 2/1/2 → 1.0 |
| B | 1.7 (10) | 15/15 | 0/2 test (không áp filter) | 1/1/3 → 1.4 |
| C | 1.7 (10, cùng chunk với B) | 15/15 | 2/2 test, 2/2 dev | 0/1/4 → 1.8 |

Các file kết quả:
- Trace top-3 đầy đủ (text, score, metadata) ở `results/traces/{A_fixed,B_struct,C_struct_filter}.jsonl`. Chỉ số tổng hợp ở `results/summary.json`.
- Nhãn chấm tay ở [`results/manual/coherence_labels.csv`](../../results/manual/coherence_labels.csv) và [`results/manual/test_audit.csv`](../../results/manual/test_audit.csv), có lý do cho từng nhãn.

Cách chọn mẫu:
- **Coherence:** 10 vị trí được cố định trong code trước khi có điểm, là điểm giữa trang của ANM trang 5/15/25/35, GDDT trang 5/15/25 và BVDLCN trang 5/15/20. Ở mỗi vị trí, chấm chunk chứa điểm đó.
- **Metadata:** kiểm tra 5 câu test nhân top-3, tức 15 bản ghi cho mỗi cấu hình. `source` và `page` được đối chiếu với PDF. `article` được dò độc lập bằng cách tìm tiêu đề "Điều N." gần nhất trong text thô của PyMuPDF.
- **Người chấm:** nhãn do trợ lý AI (Cursor) đề xuất và tôi rà soát lại. Tôi cũng là người viết benchmark, nên có nguy cơ thiên lệch.

## Phân tích và kết luận

- **A so với B (đổi cách chọn ranh giới):**
  - B tăng Hit@3 trên dev từ 14/15 lên 15/15, và tăng coherence từ 0.8 lên 1.7.
  - Chunk của A bắt đầu và kết thúc giữa chữ ("iều tra", "của lực l"). Ở vị trí pos02 và pos08, chunk A bị cắt đúng chỗ chứa nghĩa vụ hoặc mức phạt.
  - Metadata của A cũng kém tin cậy hơn. Ở A-q18, chunk bắt đầu bằng đuôi Điều 44 nên được gắn `article=44`, trong khi bằng chứng nằm ở Điều 45. Ai trích dẫn theo metadata sẽ ghi sai Điều.
  - Trên test, Hit@1 của B (1/5) thấp hơn A (2/5), nhưng đây chỉ là chênh lệch 1 câu trên 5 câu.
- **B so với C (thêm filter):**
  - Filter sửa đúng loại lỗi đã dự đoán. Không lọc, B xếp nhầm luật lên hạng 1 ở cả 4 câu chung chung. Ví dụ ở **q14**, hạng 1 là "Luật này có hiệu lực thi hành từ ngày 01 tháng 01 năm 2026" của BVDLCN, còn gold là GDDT trang 29. Ở **q20**, top-3 toàn chunk Luật An ninh mạng, trong khi gold là BVDLCN trang 1.
  - Có filter, C lấy đúng ở cả 4/4 câu. 16 câu còn lại không có filter nên cho kết quả giống hệt B.
- **Ví dụ lỗi không filter nào sửa được, q17 (test, BVDLCN trang 24):** khoản 2 Điều 38 kéo dài từ trang 24 sang trang 25.
  - Chunk hạng 1 của A có câu quy định nhưng bị cắt ở "trong thời gi", mất cụm "05 năm".
  - B và C lấy chunk ở trang 25, chỉ có phần ngoại lệ "…trừ doanh nghiệp nhỏ… kinh doanh dịch vụ xử lý dữ liệu cá nhân".
  - Cả ba cấu hình đều chỉ đạt grounding 1. Nguyên nhân là chunk bị giới hạn trong từng trang, không phải do model.
- **Chiến lược chọn: C.** C dùng chunk theo cấu trúc Điều và lọc theo văn bản khi người dùng đã chọn phạm vi.
  - Đánh đổi: B và C có nhiều chunk hơn A (320 so với 258) và chunk ngắn hơn (trung vị 654 so với 999 ký tự). Thời gian embed tương đương, và chi phí đều bằng 0 vì chạy local.
  - Filter chỉ có ích khi phạm vi văn bản được biết trước. Nếu đoán sai luật, filter sẽ loại luôn bằng chứng đúng.
- **Hạn chế:**
  - Tập test chỉ có 5 câu. Mỗi câu tương đương 20 điểm phần trăm, nên chênh lệch giữa A và B trên test không có ý nghĩa thống kê.
  - Dev và test lấy từ cùng ba văn bản. q16 và q20 có dạng câu tương tự q15 thuộc dev, nên có nguy cơ rò rỉ khuôn mẫu câu hỏi.
  - Trên 4 câu filter, giá trị filter trùng với nguồn gold. Đây là thiết kế "người dùng chọn luật", nên không thể suy rộng mức tăng của C sang câu hỏi mà người dùng không biết phạm vi.
  - Nhãn được chấm bởi một người (có AI hỗ trợ), không có người chấm thứ hai độc lập.
  - Thời gian đo trên một máy Mac, chạy CPU, mỗi cấu hình chỉ đo một lần.
- **Nếu làm lại:**
  - Cho phép chunk theo Điều vượt qua ranh giới trang, lưu `page_start` và `page_end` để sửa lỗi kiểu q17.
  - Thêm tiền tố ngữ cảnh "Luật X – Điều N. Tên Điều" vào text trước khi embed, để chunk ở đầu trang (như pos01) không mất ngữ cảnh.
  - Thử hybrid với BM25 cho các câu chứa số hiệu hoặc con số.
  - Viết thêm câu test thuộc một văn bản thứ tư chưa dùng ở dev.
