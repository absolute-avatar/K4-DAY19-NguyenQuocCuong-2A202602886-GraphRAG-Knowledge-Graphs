# Báo cáo Day 19 — Flat RAG vs GraphRAG

**Họ tên:** Nguyễn Quốc Cường  **MSSV:** 2A202602886  **Ngày:** 05/10/2026

Nguồn số liệu: [ket_qua_benchmark_kg.txt](../ket_qua_benchmark_kg.txt). Cấu hình: chat `openai:gpt-4o-mini`, embedding `openai:text-embedding-3-small`, `top_k=3`, `chunk_size=800`, **176 chunk**, **201 node / 382 cạnh**. Corpus gồm 18 Điều luật và 20 bài báo. Dùng [ontology gợi ý](ONTOLOGY.md), không đăng ký bonus tự thiết kế. Kỳ vọng nộp bài theo [SUBMISSION.md](../SUBMISSION.md).

## 1. Chi phí (10 điểm)

Hai bảng dưới giữ nguyên số liệu đã sinh trong file benchmark:

```
== Indexing (one-off)
pipeline  calls    in_tok  out_tok       USD  seconds
flat        176     56072        0   0.00112     67.7
graph       196     91958     4762   0.00936    136.9

== Querying (mean per question)
pipeline  recall  judge   in_tok  out_tok       USD  seconds
flat        0.43   1.00      694       47   0.00013     1.72
graph       0.94   1.83     3839       83   0.00062     2.72
```

| Chỉ số | Flat | Graph | Graph / Flat |
| --- | --- | --- | --- |
| Indexing USD | 0.00112 | 0.00936 | 8.36× |
| Indexing giây | 67.7 | 136.9 | 2.02× |
| Mỗi câu: USD | 0.00013 | 0.00062 | 4.77× |
| Mỗi câu: giây | 1.72 | 2.72 | 1.58× |
| Mỗi câu: in_tok | 694 | 3839 | 5.53× |

Các tỉ lệ tính từ số đã làm tròn trong file kết quả và làm tròn đến hai chữ số thập phân. USD là ước tính do code benchmark tính, không phải hóa đơn của nhà cung cấp; bảng không bao gồm chi phí vận hành Neo4j.

**Chi phí tăng thêm đến từ đâu?** Graph indexing bao gồm cùng phần embedding của Flat RAG và thêm 20 lần gọi LLM trích xuất tin, tăng 0.00824 USD và 69.2 giây; luật được tách bằng regex. Khi hỏi, GraphRAG đưa thêm dữ kiện và nội dung khoản luật vào prompt, khiến input trung bình tăng từ 694 lên 3839 token, chi phí tăng khoảng 0.00049 USD/câu. Các lần gọi LLM judge được benchmark đo riêng và không cộng vào chi phí pipeline trong hai bảng.

**Điểm hòa vốn về chi phí:** với số đo hiện tại, không có số câu hỏi dương nào làm GraphRAG rẻ hơn Flat RAG, vì cả phí khởi tạo lẫn phí mỗi câu đều cao hơn. Với N câu hỏi, chênh lệch ước tính là `0.00824 + 0.00049 × N` USD; lợi ích cần đánh đổi là chất lượng trả lời, không phải tiết kiệm tiền. Đây là ngoại suy từ sáu câu trong một lần chạy, chưa phải dự báo ổn định cho mọi workload.

## 2. Từng câu hỏi (10 điểm)

| Câu | Loại | Flat recall / judge | Graph recall / judge | Thắng | Vì sao (1 câu) |
| --- | --- | --- | --- | --- | --- |
| Q1 | single-hop-law | 1.00 / 2 | 1.00 / 2 | Hòa về chất lượng | Cả hai lấy được định nghĩa tiền chất; GraphRAG bổ sung Điều 2, khoản 4 nhưng Flat RAG đã đủ đáp án. |
| Q2 | single-hop-news | 1.00 / 2 | 1.00 / 2 | Hòa về chất lượng | Cả hai nêu đúng Trần Thanh Tuấn và Trần Minh Tâm; thông tin nằm ngay trong bài báo. |
| Q3 | cross-kb | 0.00 / 0 | 1.00 / 2 | Graph | Flat trả “Không đủ thông tin”; Graph nối mức án 36 tháng của Thành với Điều 251 và khung 02–07 năm. |
| Q4 | cross-kb | 0.00 / 0 | 1.00 / 2 | Graph | Graph tìm qua biệt danh và lấy khoản 4 Điều 255 có chung thân; Flat không đủ thông tin. |
| Q5 | cross-kb-multi-hop | 0.60 / 1 | 1.00 / 2 | Graph theo phép chấm | Graph nêu đúng Điều 250 khoản 4; Flat chỉ ghi “khoản b)”, nhưng cả hai còn bỏ Ketamine so với gold, xem E4. |
| Q6 | aggregation | 0.00 / 1 | 0.67 / 1 | Graph về recall; hòa judge | Graph nêu đủ tên Huy và Thành, nhưng chưa nêu Viện Pháp y tâm thần; cả hai đều chỉ được judge 1. |

Trên nhóm Q3–Q5, recall trung bình của Flat là 0.20, Graph là 1.00; judge tương ứng khoảng 0.33 và 2.00. Q1–Q2 không có lợi thế chất lượng đo được từ graph, còn Q6 cho thấy truy vấn toàn graph chưa bảo đảm LLM tổng hợp đủ. Cột “Thắng” mô tả kết quả đo, không thay thế việc đọc thủ công câu trả lời; recall 0 của Q6 Flat cũng không có nghĩa câu trả lời hoàn toàn không chứa thông tin đúng, vì phép đo yêu cầu chuỗi tên đầy đủ.

## 3. Phân tích lỗi (20 điểm)

Phân tích dựa trên [kết quả benchmark](../ket_qua_benchmark_kg.txt), ảnh đã chụp và kết quả truy vấn đã ghi nhận ở Bước 8 (201 node, 382 cạnh). Số liệu benchmark được giữ nguyên. Cypher và các kết quả dùng làm bằng chứng được trình bày ngay dưới đây; xem thêm [ghi chép Bước 8](STEP8.md).

### Lỗi E3: chất trùng tên chuẩn và vụ bị tách theo bài báo

- **Hiện tượng:** cùng một chất có hai node chỉ khác chữ hoa/thường. Cùng vụ vận chuyển của Cái Quang Huy cũng thành hai Case trong kết quả tổng hợp MDMA.
- **Bằng chứng:** truy vấn trên graph hiện tại:

```cypher
MATCH (s:Substance)
WITH toLower(s.name) AS normalized, collect(s.name) AS names
WHERE size(names) > 1
RETURN normalized, names ORDER BY normalized;
```

| normalized | names |
| --- | --- |
| ketamine | [Ketamine, ketamine] |
| methamphetamine | [Methamphetamine, methamphetamine] |

Truy vấn Q6 ở phần E5 còn trả hai dòng cho Huy: `Vụ vận chuyển ma túy từ Đức về Việt Nam` (`news-100260917203001265`) và `Vụ vận chuyển ma túy của Cái Quang Huy` (`news-100260918080821054`). Dòng sau đến từ bài về Lê Minh Thành; đoạn cuối bài đó giới thiệu lại vụ Huy, với cùng người, tuyến Đức–Nội Bài và hơn 9,6kg MDMA.

- **Nguyên nhân:** tại KG-2 trong `src/graph.py`, `extract_news_cases` chỉ hậu kiểm tội danh, chưa chuẩn hóa tên chất. `add_news_case` MERGE Substance bằng `name` nguyên bản nên khác chữ hoa/thường tạo node khác. Case cũng MERGE theo tên tự do do LLM đặt; prompt chưa loại rõ đoạn dẫn sang bài khác. Lỗi bắt đầu từ nội dung crawl lẫn đoạn liên quan, sau đó đi qua prompt trích xuất và khóa định danh của ontology.
- **Đề xuất sửa:** chuẩn hóa Unicode/chữ hoa/thường và map tên chất về `SUBSTANCES` trước khi ghi; không tự đồng nhất “thuốc lắc” với MDMA khi không có xác nhận thành phần. Bổ sung quy tắc bỏ đoạn giới thiệu bài liên quan trong prompt/tiền xử lý. Về lâu dài, thêm ID vụ và danh sách nguồn sau khi đối chiếu người, sự kiện, thời gian. Chuẩn hóa chuỗi ít tốn chi phí; hợp nhất vụ cần thêm logic hoặc bước xác minh và có nguy cơ gộp nhầm. Nếu đổi khóa/schema phải cập nhật ONTOLOGY.md và dựng lại graph.

### Lỗi E4: điểm tối đa vẫn bỏ sót một loại ma túy

- **Hiện tượng:** Q5 GraphRAG được `recall=1.00`, `judge=2`, nhưng chỉ nêu MDMA, không nêu Ketamine dù câu hỏi hỏi các loại ma túy trong vụ và gold có cả hai.
- **Bằng chứng:** câu trả lời Q5 GraphRAG trong file benchmark:

> Cái Quang Huy bị truy tố về tội vận chuyển trái phép chất ma túy với loại ma túy là MDMA. Với khối lượng MDMA là hơn 9,6kg, điều luật tương ứng được áp dụng là Điều 250 BLHS khoản 4. Khung hình phạt là 20 năm, tù chung thân hoặc tử hình.

Trong `data/benchmark_kg.json`, gold Q5 có `hơn 9,6kg MDMA và khoảng 406g Ketamine`, còn `must_include` chỉ gồm `vận chuyển`, `MDMA`, `Điều 250`, `khoản 4`, `tử hình`. Nguồn `data/drug_news/news-100260917203001265.md` cũng nêu rõ tổng lượng MDMA và khoảng 406g Ketamine.

- **Nguyên nhân:** `keyword_recall` trong `bench_kg.py` chỉ kiểm tra sự xuất hiện của từng chuỗi trong `must_include`; không có Ketamine trong danh sách nên điểm 1.00 không chứng minh trả lời đủ mọi ý. LLM judge cũng cho điểm tối đa trong lần này, cho thấy phép chấm tổng thể có thể bỏ sót chi tiết. Đây không phải trường hợp recall/judge đối nghịch, mà là thiếu sót cả hai phép đo chưa phát hiện.
- **Đề xuất sửa:** với bộ đánh giá mở rộng riêng, chấm từng ý: tội danh, hai loại chất, lượng MDMA, Điều/khoản và hình phạt; yêu cầu judge giải thích ý thiếu thay vì chỉ lưu score. Điều này tăng token chấm và công sức xây rubric; vẫn cần kiểm tra thủ công. Không sửa benchmark chuẩn hay kết quả đã sinh của bài nộp để làm điểm tăng.

### Lỗi E5: Q6 chưa nêu rõ vụ Viện Pháp y tâm thần trong câu trả lời

- **Hiện tượng:** Q6 GraphRAG đạt `recall=0.67`, `judge=1`; liệt kê Huy, Thành và vụ Sầm Sơn, nhưng không nêu tên vụ Viện Pháp y tâm thần có trong graph và đáp án chuẩn.
- **Bằng chứng:** mục thứ ba của câu trả lời Q6 GraphRAG trong file benchmark:

> 3. **Vụ tổ chức sử dụng ma túy tại Sầm Sơn**: Lê Văn Đông bị cáo buộc có liên quan đến 0,686g MDMA.

Truy vấn trực tiếp không giới hạn theo vector top-k:

```cypher
MATCH (k:Case)-[r:INVOLVES]->(:Substance {name:'MDMA'})
OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(k)
RETURN k.name AS name, k.doc_id AS doc_id, k.summary AS summary,
       r.amount AS amount, collect(DISTINCT p.name) AS people
ORDER BY doc_id, name;
```

Bảng dưới ghi ba cột nhận diện vụ và khối lượng từ năm dòng kết quả truy vấn đã quan sát ở Bước 8:

| Case | doc_id | amount |
| --- | --- | --- |
| Vụ vận chuyển ma túy từ Đức về Việt Nam | news-100260917203001265 | 9.6kg |
| Vụ góp tiền mua ma túy tại Hà Nội | news-100260918080821054 | 5 viên |
| Vụ vận chuyển ma túy của Cái Quang Huy | news-100260918080821054 | 9,6kg |
| Vụ án tại Viện Pháp y tâm thần Trung ương | news-100260924105118645 | chuỗi rỗng |
| Vụ tổ chức sử dụng ma túy tại Sầm Sơn | news-100260930085028036 | 0,686g |

`context(Q6, [])` tính lại trên graph hiện tại trả 30 dòng, có tên Viện Pháp y tâm thần. Nguồn `news-100260930085028036` ghi 0,686g MDMA thu tại **buồng chữa bệnh trong viện**; việc gắn lượng này với Case có tên Sầm Sơn đã làm mờ nơi thu giữ. Năm node không tương đương năm vụ độc lập: Huy bị lặp, còn hai Case cuối là các phần liên quan của vụ ở viện.

- **Nguyên nhân:** schema gắn Substance/amount ở cấp Case, chưa có sự kiện/nơi thu giữ; tên Case do LLM đặt và trùng hồ sơ tạo context dễ nhầm khi tổng hợp. Prompt trả lời chưa yêu cầu giữ nguồn và phân biệt sự kiện khi nhóm vụ. Bằng chứng hiện tại cho thấy graph có dữ kiện mà câu trả lời thiếu; chưa lưu prompt của lần benchmark nên chưa thể quy toàn bộ nguyên nhân cho LLM hoặc loại trừ khác biệt context tại thời điểm chạy.
- **Đề xuất sửa:** cho câu aggregation, tổng hợp danh sách có `doc_id`, tên vụ và chứng cứ liên quan trước khi viết câu trả lời; nhóm hồ sơ cùng vụ khi có căn cứ và giữ rõ nơi thu giữ trong summary. Có thể bổ sung sự kiện thu giữ khi mở rộng ontology. Tại `GraphRAGAgent.answer`/`GRAPH_PROMPT`, yêu cầu không bỏ nhóm có chứng cứ và dẫn nguồn mỗi mục. Cần lưu prompt/facts cho từng lần đánh giá để phân biệt lỗi retrieval với lỗi sinh câu trả lời; lưu thêm trace tốn dung lượng, context có nguồn sẽ dài hơn. Chưa chạy lần benchmark thứ hai nên chưa kết luận lỗi có lặp ổn định.

## 4. Kết luận (5 điểm)

Với corpus và cấu hình này, **GraphRAG phù hợp cho câu hỏi cần nối tin tức với điều luật**, đặc biệt Q3–Q5: recall tăng từ 0.20 lên 1.00 trong nhóm này. Node Crime giúp nối người/vụ tới Điều luật ngay cả khi các chunk top-k chỉ chứa bài báo; lấy toàn bộ khoản khi hỏi mức tối đa giúp tránh thiếu khung cao nhất ở Q4.

**Flat RAG đủ cho tra cứu cục bộ như Q1–Q2**: cả hai pipeline cùng đạt recall 1.00, judge 2. Nếu phần lớn câu hỏi có đáp án trong một đoạn nguồn, mức chi phí trung bình 0.00013 USD/câu của Flat thuận lợi hơn 0.00062 USD/câu của Graph, trong khi indexing cũng thấp hơn 8.36 lần theo số đo hiện tại.

Trên cả sáu câu, Graph nâng recall trung bình từ 0.43 lên 0.94 và judge từ 1.00 lên 1.83, đổi lại thời gian hỏi trung bình tăng từ 1.72 lên 2.72 giây. **Chưa thể kết luận graph luôn tốt hơn:** E3 cho thấy dữ liệu trùng, E4 cho thấy điểm tối đa vẫn bỏ ý và Q6 vẫn chỉ đạt judge 1. Khi nhiều câu hỏi cần tổng hợp theo thực thể, nên ưu tiên cải thiện chuẩn hóa và quản lý nguồn trước khi mở rộng graph; một lần chạy trên sáu câu chưa đủ để suy ra độ ổn định hoặc hiệu quả ở quy mô lớn.

## 5. Tự kiểm (5 điểm)

Kết quả chạy lại trên workspace ngày 05/10/2026:

```text
$ .\.venv\Scripts\python.exe -m pytest tests/ -q
................................................                         [100%]
48 passed in 0.80s
```

**`python bench_kg.py --check` — kết quả lần kiểm tra đã ghi nhận:**

```text
[OK] Dữ liệu: 18 điều luật, 20 bài báo
[OK] KG-1 link_entity
[OK] Neo4j kết nối được
[provider] chat = openai:gpt-4o-mini | embedding = openai:text-embedding-3-small
```

Lệnh dừng ở kết nối API với `openai.APIConnectionError: Connection error.`; đây là phần output trước lỗi, không phải một lần kiểm tra đạt đủ 7 dòng `[OK]`. Ảnh và file benchmark không chứa log `--check` thành công nên báo cáo không suy diễn kết quả này. Mục tự kiểm còn giới hạn bằng chứng đó so với yêu cầu của Submission.

Đã thực hiện thêm **kiểm tra chỉ đọc trên graph đầy đủ**, không gọi API và không thay đổi dữ liệu. Kết quả đã ghi nhận: đủ 7 label/7 quan hệ; Article/Clause/Case có `doc_id`; đường xuyên KB dài 2 cạnh; `context()` có Điều 251; `answer()` ghép đủ graph/chunk/câu hỏi với LLM giả lập. Kiểm tra này bổ sung bằng chứng, **không thay thế** lệnh `--check` chuẩn hoặc kiểm tra trích xuất LLM.

| Ảnh | Nội dung | Quan sát từ ảnh |
| --- | --- | --- |
| [kg_count.png](img/kg_count.png) | Q-A: đủ 7 label, tổng 201 node | Clause 99, Person 34, Article 18, Substance 17, Case 14, Crime 13, Location 6. |
| [kg_cross_kb.png](img/kg_cross_kb.png) | Q-B: đường đi xuyên hai KB | Có đường Person → Case → Crime ← Article và truy vấn `LIMIT 25`; cột phải đang hiển thị Node details. |
| [kg_my_case.png](img/kg_my_case.png) | Q-D: vụ của Phan Kim Nhi | Results overview: Article 2, Case 3, Crime 2, Location 1, Person 1, Substance 1; tổng 10 node/15 cạnh trong kết quả. |

Người đã chọn cho `kg_my_case.png`: **Phan Kim Nhi**.

Số tổng của database trong bộ ảnh là **201 node / 382 cạnh**, khớp benchmark. Số node/cạnh riêng trong khung kết quả Q-B/Q-D chỉ là phần graph được truy vấn. Đường từ người qua một Case có nhiều tội không đồng nghĩa người đó bị gán tất cả tội; khi trả lời theo người, code lọc thêm `INVOLVED_IN.charge`.

Ảnh được giữ nguyên như đã cung cấp. Ghi nhận về quy cách: Q-A còn khung `:welcome`, Q-B không mở Results overview và Q-D đang thu gọn một phần câu Cypher. Các điểm này được ghi lại trong [STEP8.md](STEP8.md), không dùng để thay đổi số liệu hoặc khẳng định đã đạt toàn bộ tiêu chí ảnh của [Submission](../SUBMISSION.md).

## Vấn đề gặp phải (không tính điểm)

Lệnh `python bench_kg.py --check` từng kết nối được Neo4j nhưng thất bại ở lời gọi LLM vì sandbox chặn socket. Các dòng cuối thông báo đã quan sát (trích, không phải toàn bộ traceback):

```text
httpx.ConnectError: [WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions
openai.APIConnectionError: Connection error.
```

Kiểm tra bổ sung chỉ đọc xác nhận graph đầy đủ 201 node/382 cạnh, có dữ liệu hai KB và ghép được prompt GraphRAG; chưa có log `--check` thành công trong tài liệu được cung cấp. Các hạn chế chất lượng E3–E5 được giữ lại để phân tích, chưa tuyên bố đã sửa hay chạy benchmark lần hai.
