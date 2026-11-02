BEGIN TRANSACTION;
CREATE TABLE audits(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE dataset_annotations(
          code TEXT NOT NULL, annotator TEXT NOT NULL, label TEXT NOT NULL,
          issue_type TEXT, severity TEXT, timestamp TEXT, notes TEXT, created_at TEXT NOT NULL,
          PRIMARY KEY (code, annotator));
CREATE TABLE dataset_cases(
          code TEXT PRIMARY KEY, case_group TEXT NOT NULL, base_code TEXT, sku TEXT,
          name TEXT, brand TEXT, price INTEGER, price_raw TEXT, variant TEXT,
          product_context TEXT, approved_claims TEXT, data_origin TEXT,
          source_url TEXT, product_url TEXT, platform TEXT, issue_type TEXT,
          description TEXT, expected TEXT, observed TEXT, location TEXT,
          severity TEXT, source_status TEXT, expected_truth TEXT, truth_origin TEXT,
          source_annotator TEXT, product_id TEXT, verified_truth TEXT, verified_by TEXT,
          updated_at TEXT NOT NULL);
CREATE TABLE dataset_imports(
          id TEXT PRIMARY KEY, checksum TEXT NOT NULL, created_at TEXT NOT NULL,
          case_count INTEGER NOT NULL, note TEXT NOT NULL);
CREATE TABLE dataset_rules(
          rule_id TEXT PRIMARY KEY, name TEXT, source_type TEXT, source_reference TEXT,
          linked_error_code TEXT, severity TEXT, verification_status TEXT, notes TEXT);
CREATE TABLE dataset_simulated(
          code TEXT PRIMARY KEY, source_sheet TEXT NOT NULL, truth TEXT,
          truth_type TEXT, prediction TEXT, prediction_type TEXT, classification TEXT);
CREATE TABLE evidence(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,kind TEXT NOT NULL,timestamp REAL NOT NULL,content TEXT NOT NULL,score REAL,frame TEXT, end_timestamp REAL, frame2 TEXT, source_model TEXT, fingerprint TEXT, metadata TEXT NOT NULL DEFAULT '{}');
CREATE TABLE findings(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,code TEXT NOT NULL,severity TEXT NOT NULL,timestamp REAL NOT NULL,detail TEXT NOT NULL,evidence_id INTEGER,flag_review TEXT DEFAULT 'unreviewed', source TEXT NOT NULL DEFAULT 'rule', confidence REAL, evidence_refs TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}');
CREATE TABLE jobs(id TEXT PRIMARY KEY,filename TEXT NOT NULL,stored_name TEXT NOT NULL,product_id TEXT NOT NULL,status TEXT NOT NULL,decision TEXT,review_decision TEXT,reviewer TEXT,review_note TEXT,source_url TEXT,rights TEXT,created_at TEXT NOT NULL,finished_at TEXT,details TEXT NOT NULL, case_code TEXT, recovery_attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE labels(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,annotator TEXT NOT NULL,label TEXT NOT NULL,notes TEXT,created_at TEXT NOT NULL);
CREATE TABLE product_import_profiles(
            product_id TEXT PRIMARY KEY,
            video_code TEXT NOT NULL,
            variant TEXT NOT NULL,
            expected_video_description TEXT NOT NULL,
            source_class TEXT NOT NULL,
            owner TEXT NOT NULL,
            notes TEXT NOT NULL,
            import_sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            created_by_import INTEGER NOT NULL DEFAULT 0);
INSERT INTO "product_import_profiles" VALUES('4d5d80737d66','VID_GOC01','200ml','Có cầm chai, bơm sữa tắm ra lòng bàn tay','Giả lập (ví dụ minh họa)','','Video gốc dùng làm nền để tạo các video lỗi ở Sheet 2 (VID_LOI...)','57dd9c099666064762dd1c1c86057646d693bdfb58c7595aa4ffd5207193c0cd','2026-10-30T17:27:53+00:00',0);
INSERT INTO "product_import_profiles" VALUES('a7ce412d6365','VID_GOC02','240ml','Chỉ có tay cầm và nghịch cái núm ti. Bình trống suốt video, không có cảnh rót sữa. Chữ “MiniFeed” trên bình bị méo/nhảy ở giây 3–4','Giả lập (ví dụ minh họa)','','','57dd9c099666064762dd1c1c86057646d693bdfb58c7595aa4ffd5207193c0cd','2026-10-30T17:27:53+00:00',0);
INSERT INTO "product_import_profiles" VALUES('f6c554f0e30f','VID_GOC03','Size M (6-11kg)','Có cầm gói và xé miệng gói. Cuối video chỉ thấy mép trắng ló ra, không rút hay cho xem miếng tã nào. Giây 0–3 gói tã nằm ngang rồi chuyển sang dựng đứng bằng một cú mờ chồng hình. Video không có âm thanh','Giả lập (ví dụ minh họa)','','','57dd9c099666064762dd1c1c86057646d693bdfb58c7595aa4ffd5207193c0cd','2026-10-30T17:27:53+00:00',0);
INSERT INTO "product_import_profiles" VALUES('0815cfe1a5cf','VID_GOC04','Hộp 900g, 0-6 tháng','Chỉ có tay cầm, nhấc rồi đặt hộp xuống. Không có muỗng, không có sữa bột','Giả lập (ví dụ minh họa)','','','57dd9c099666064762dd1c1c86057646d693bdfb58c7595aa4ffd5207193c0cd','2026-10-30T17:27:53+00:00',0);
INSERT INTO "product_import_profiles" VALUES('31bbffc9b174','VID_GOC05','Gói 80 tờ','Mở nắp, rút 1 tờ khăn ra','Giả lập (ví dụ minh họa)','','','57dd9c099666064762dd1c1c86057646d693bdfb58c7595aa4ffd5207193c0cd','2026-10-30T17:27:53+00:00',0);
INSERT INTO "product_import_profiles" VALUES('ca5c8aee6de0','VID_GOC06','Tuýp 50g','Video quay cảnh cầm tuýp kem, cảnh bôi lên tay, đọc đúng tên và giá','Giả lập (ví dụ minh họa)','','','57dd9c099666064762dd1c1c86057646d693bdfb58c7595aa4ffd5207193c0cd','2026-10-30T17:27:53+00:00',0);
CREATE TABLE product_truth_audits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            event TEXT NOT NULL,
            revision INTEGER NOT NULL,
            snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL);
INSERT INTO "product_truth_audits" VALUES(1,'f6c554f0e30f','updated',2,'{"sku": "SKU003", "name": "Tã dán", "brand": "SoftDry", "price": 259000, "claims": ["Thấm hút nhanh", "Không gây hăm"], "banned": [], "reference_url": "", "reference_note": "", "reference_status": "unverified"}','2026-10-30T17:08:48+00:00');
INSERT INTO "product_truth_audits" VALUES(2,'31bbffc9b174','updated',2,'{"sku": "SKU005", "name": "Khăn ướt", "brand": "PureSoft", "price": 45000, "claims": ["Không cồn, không hương liệu", "Dịu nhẹ cho da nhạy cảm"], "banned": [], "reference_url": "", "reference_note": "", "reference_status": "unverified"}','2026-10-30T17:25:57+00:00');
INSERT INTO "product_truth_audits" VALUES(3,'ca5c8aee6de0','updated',2,'{"sku": "SKU006", "name": "Kem dưỡng da mặt", "brand": "BabySkin", "price": 89000, "claims": ["Chiết xuất oxit kẽm", "Ngăn ngừa hăm tã"], "banned": [], "reference_url": "", "reference_note": "", "reference_status": "unverified"}','2026-10-30T17:27:35+00:00');
INSERT INTO "product_truth_audits" VALUES(4,'31bbffc9b174','updated',3,'{"sku": "SKU005", "name": "Khăn ướt", "brand": "PureSoft", "price": 45000, "claims": ["Không cồn, không hương liệu", "Dịu nhẹ cho da nhạy cảm"], "banned": [], "reference_url": "", "reference_note": "", "reference_status": "unverified"}','2026-10-30T18:02:32+00:00');
INSERT INTO "product_truth_audits" VALUES(5,'4d5d80737d66','updated',2,'{"sku": "SKU001", "name": "Sữa tắm gội toàn thân", "brand": "BabyGentle", "price": 149000, "claims": ["Dịu nhẹ cho da bé", "Không gây kích ứng", "Chiết xuất thiên nhiên"], "banned": [], "reference_url": "", "reference_note": "", "reference_status": "unverified"}','2026-10-30T19:35:02+00:00');
INSERT INTO "product_truth_audits" VALUES(6,'4d5d80737d66','updated',3,'{"sku": "SKU001", "name": "Sữa tắm gội toàn thân", "brand": "BabyGentle", "price": 149000, "claims": ["Dịu nhẹ cho da bé", "Không gây kích ứng", "Chiết xuất thiên nhiên"], "banned": [], "reference_url": "", "reference_note": "", "reference_status": "unverified"}','2026-10-30T20:29:25+00:00');
INSERT INTO "product_truth_audits" VALUES(7,'31bbffc9b174','updated',4,'{"sku": "SKU005", "name": "Khăn ướt", "brand": "PureSoft", "price": 45000, "claims": ["Không cồn, không hương liệu", "Dịu nhẹ cho da nhạy cảm"], "banned": [], "reference_url": "", "reference_note": "", "reference_status": "unverified"}','2026-10-30T20:40:32+00:00');
INSERT INTO "product_truth_audits" VALUES(8,'f6c554f0e30f','updated',3,'{"sku": "SKU003", "name": "Tã dán", "brand": "SoftDry", "price": 259000, "claims": ["Thấm hút nhanh", "Không gây hăm"], "banned": [], "reference_url": "", "reference_note": "", "reference_status": "unverified"}','2026-10-30T20:51:48+00:00');
INSERT INTO "product_truth_audits" VALUES(9,'4d5d80737d66','updated',4,'{"sku": "SKU001", "name": "Sữa tắm gội toàn thân", "brand": "BabyGentle", "price": 149000, "claims": ["Dịu nhẹ cho da bé", "Không gây kích ứng", "Chiết xuất thiên nhiên"], "banned": [], "reference_url": "", "reference_note": "", "reference_status": "unverified"}','2026-10-31T02:21:53+00:00');
INSERT INTO "product_truth_audits" VALUES(10,'26cfd5b3c113','created',1,'{"sku": "SKU007", "name": "Ghế ăn dặm Abiie Beyond Junior® Y High Chair (ghế gỗ điều chỉnh độ cao)", "brand": "Abiie", "price": 238, "claims": ["High Chair: chất liệu gỗ beech châu Âu;", "EZ-Seat điều chỉnh chiều cao ghế và chỗ để chân;", "khay tháo rời, đệm chống thấm và hệ thống dây đai 3/5 điểm;", "dùng từ khoảng 6 tháng tới giai đoạn lớn hơn theo mô tả hãng."], "banned": [], "reference_url": "https://www.abiie.com/products/beyond-junior-high-chair", "reference_note": "Trang web thông tin sản phẩm", "reference_status": "test_reference_approved"}','2026-10-31T02:35:21+00:00');
INSERT INTO "product_truth_audits" VALUES(11,'26cfd5b3c113','updated',2,'{"sku": "SKU007", "name": "Ghế ăn dặm Abiie Beyond Junior® Y High Chair (ghế gỗ điều chỉnh độ cao)", "brand": "Abiie", "price": 237984, "claims": ["High Chair: chất liệu gỗ beech châu Âu;", "EZ-Seat điều chỉnh chiều cao ghế và chỗ để chân;", "khay tháo rời, đệm chống thấm và hệ thống dây đai 3/5 điểm;", "dùng từ khoảng 6 tháng tới giai đoạn lớn hơn theo mô tả hãng."], "banned": [], "reference_url": "https://www.abiie.com/products/beyond-junior-high-chair", "reference_note": "Trang web thông tin sản phẩm", "reference_status": "test_reference_approved"}','2026-10-31T02:35:48+00:00');
INSERT INTO "product_truth_audits" VALUES(12,'26cfd5b3c113','updated',3,'{"sku": "SKU007", "name": "Ghế ăn dặm Abiie Beyond Junior® Y High Chair (ghế gỗ điều chỉnh độ cao)", "brand": "Abiie", "price": 237984, "claims": ["High Chair: chất liệu gỗ beech châu Âu;", "EZ-Seat điều chỉnh chiều cao ghế và chỗ để chân;", "khay tháo rời, đệm chống thấm và hệ thống dây đai 3/5 điểm;", "dùng từ khoảng 6 tháng tới giai đoạn lớn hơn theo mô tả hãng."], "banned": [], "reference_url": "https://www.abiie.com/products/beyond-junior-high-chair", "reference_note": "Trang web thông tin sản phẩm", "reference_status": "test_reference_approved"}','2026-10-31T02:43:22+00:00');
INSERT INTO "product_truth_audits" VALUES(13,'481bbeca959a','created',1,'{"sku": "SKU008", "name": "TendeRoo Baby Nappy Care Cream 20g – tuýp kem chăm sóc vùng tã", "brand": "TendeRoo Nappy", "price": 109, "claims": ["Safe and gentle for newborn baby", "Relieves diapers redness and skin discomfort", "Builds a protective barrier to reduce skin irritation", "Prevents redness and sensitivity, strengthens skins barrier", "Infused with natural botanicals to nourish healthy skin", "Free from artificial fragance, colorants and parabens"], "banned": [], "reference_url": "https://shopee.ph/Tenderoo-Baby-Nappy-Care-Cream-20g-Diaper-Rash-Cream-Moisturizing-Skin-Barrier-Care-for-Babies-i.1814649621.57513673428?extraParams=%7B%22display_model_id%22%3A401183346627%2C%22model_selection_logic%22%3A3%7D&image_ids=sg-11134201-8258w-mqfyh9wir8y30f", "reference_note": "", "reference_status": "test_reference_approved"}','2026-10-31T02:53:14+00:00');
CREATE TABLE product_truth_meta(
            product_id TEXT PRIMARY KEY,
            reference_url TEXT NOT NULL DEFAULT '',
            reference_note TEXT NOT NULL DEFAULT '',
            reference_status TEXT NOT NULL DEFAULT 'unverified',
            revision INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL);
INSERT INTO "product_truth_meta" VALUES('f6c554f0e30f','','Bộ chuẩn kiểm thử đồ án VerifAI (video tự tạo), PO duyệt làm chuẩn kiểm thử ngày 02/11/2026; không phải xác minh thương mại.','test_reference_approved',3,'2026-11-02T03:31:49.122561+00:00');
INSERT INTO "product_truth_meta" VALUES('31bbffc9b174','','Bộ chuẩn kiểm thử đồ án VerifAI (video tự tạo), PO duyệt làm chuẩn kiểm thử ngày 02/11/2026; không phải xác minh thương mại.','test_reference_approved',4,'2026-11-02T03:31:49.122561+00:00');
INSERT INTO "product_truth_meta" VALUES('ca5c8aee6de0','','Bộ chuẩn kiểm thử đồ án VerifAI (video tự tạo), PO duyệt làm chuẩn kiểm thử ngày 02/11/2026; không phải xác minh thương mại.','test_reference_approved',2,'2026-11-02T03:31:49.122561+00:00');
INSERT INTO "product_truth_meta" VALUES('4d5d80737d66','','Bộ chuẩn kiểm thử đồ án VerifAI (video tự tạo), PO duyệt làm chuẩn kiểm thử ngày 02/11/2026; không phải xác minh thương mại.','test_reference_approved',4,'2026-11-02T03:31:49.122561+00:00');
INSERT INTO "product_truth_meta" VALUES('26cfd5b3c113','https://www.abiie.com/products/beyond-junior-high-chair','Trang web thông tin sản phẩm','test_reference_approved',3,'2026-11-02T03:31:49.122561+00:00');
INSERT INTO "product_truth_meta" VALUES('481bbeca959a','https://shopee.ph/Tenderoo-Baby-Nappy-Care-Cream-20g-Diaper-Rash-Cream-Moisturizing-Skin-Barrier-Care-for-Babies-i.1814649621.57513673428?extraParams=%7B%22display_model_id%22%3A401183346627%2C%22model_selection_logic%22%3A3%7D&image_ids=sg-11134201-8258w-mqfyh9wir8y30f','Bộ chuẩn kiểm thử đồ án VerifAI (video tự tạo), PO duyệt làm chuẩn kiểm thử ngày 02/11/2026; không phải xác minh thương mại.','test_reference_approved',1,'2026-11-02T03:31:49.122561+00:00');
INSERT INTO "product_truth_meta" VALUES('0815cfe1a5cf','','Bộ chuẩn kiểm thử đồ án VerifAI (video tự tạo), PO duyệt làm chuẩn kiểm thử ngày 02/11/2026; không phải xác minh thương mại.','test_reference_approved',1,'2026-11-02T03:31:49.122561+00:00');
INSERT INTO "product_truth_meta" VALUES('a7ce412d6365','','Bộ chuẩn kiểm thử đồ án VerifAI (video tự tạo), PO duyệt làm chuẩn kiểm thử ngày 02/11/2026; không phải xác minh thương mại.','test_reference_approved',1,'2026-11-02T03:31:49.122561+00:00');
CREATE TABLE products(id TEXT PRIMARY KEY,sku TEXT NOT NULL,name TEXT NOT NULL,brand TEXT NOT NULL,price INTEGER,claims TEXT NOT NULL,banned TEXT NOT NULL,created_at TEXT NOT NULL);
INSERT INTO "products" VALUES('4d5d80737d66','SKU001','Sữa tắm gội toàn thân','BabyGentle',149000,'["Dịu nhẹ cho da bé", "Không gây kích ứng", "Chiết xuất thiên nhiên"]','[]','2026-10-15T05:07:31+00:00');
INSERT INTO "products" VALUES('a7ce412d6365','SKU002','Bình sữa','MiniFeed',199000,'["Núm ti mềm, chống sặc", "Van chống đầy hơi"]','[]','2026-10-15T05:07:31+00:00');
INSERT INTO "products" VALUES('f6c554f0e30f','SKU003','Tã dán','SoftDry',259000,'["Thấm hút nhanh", "Không gây hăm"]','[]','2026-10-15T05:07:31+00:00');
INSERT INTO "products" VALUES('0815cfe1a5cf','SKU004','Sữa bột','NutriGrow',450000,'["Bổ sung DHA", "Hỗ trợ tiêu hóa"]','[]','2026-10-15T05:07:31+00:00');
INSERT INTO "products" VALUES('31bbffc9b174','SKU005','Khăn ướt','PureSoft',45000,'["Không cồn, không hương liệu", "Dịu nhẹ cho da nhạy cảm"]','[]','2026-10-15T05:07:31+00:00');
INSERT INTO "products" VALUES('ca5c8aee6de0','SKU006','Kem dưỡng da mặt','BabySkin',89000,'["Chiết xuất oxit kẽm", "Ngăn ngừa hăm tã"]','[]','2026-10-15T05:07:31+00:00');
INSERT INTO "products" VALUES('26cfd5b3c113','SKU007','Ghế ăn dặm Abiie Beyond Junior® Y High Chair (ghế gỗ điều chỉnh độ cao)','Abiie',237984,'["High Chair: chất liệu gỗ beech châu Âu;", "EZ-Seat điều chỉnh chiều cao ghế và chỗ để chân;", "khay tháo rời, đệm chống thấm và hệ thống dây đai 3/5 điểm;", "dùng từ khoảng 6 tháng tới giai đoạn lớn hơn theo mô tả hãng."]','[]','2026-10-31T02:35:21+00:00');
INSERT INTO "products" VALUES('481bbeca959a','SKU008','TendeRoo Baby Nappy Care Cream 20g – tuýp kem chăm sóc vùng tã','TendeRoo Nappy',109,'["Safe and gentle for newborn baby", "Relieves diapers redness and skin discomfort", "Builds a protective barrier to reduce skin irritation", "Prevents redness and sensitivity, strengthens skins barrier", "Infused with natural botanicals to nourish healthy skin", "Free from artificial fragance, colorants and parabens"]','[]','2026-10-31T02:53:14+00:00');
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('audits',291);
INSERT INTO "sqlite_sequence" VALUES('evidence',2906);
INSERT INTO "sqlite_sequence" VALUES('findings',110);
INSERT INTO "sqlite_sequence" VALUES('labels',3);
INSERT INTO "sqlite_sequence" VALUES('product_truth_audits',13);
COMMIT;
