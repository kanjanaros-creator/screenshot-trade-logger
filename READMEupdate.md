# Screenshot Trade Logger Bot (Telegram) — MVP

บอทนี้ช่วย **เก็บบันทึกการเทรดจากรูปแคปหน้าจอ** (Binance / Binance TH / MEXC / Pionex — รองรับไทย/อังกฤษ) 
โดยใช้ OCR เพื่อดึงข้อมูล **คู่เหรียญ, ซื้อ/ขาย, ราคา, ปริมาณ, ค่าธรรมเนียม, เวลา**
จากนั้นจะคำนวณ **ต้นทุนเฉลี่ย, สถานะคงเหลือ (position), และกำไร/ขาดทุนที่รับรู้ (realized P&L)** ให้โดยอัตโนมัติ

> จุดเด่น: แค่ส่งรูปให้บอทใน Telegram ➜ บอทตอบกลับสรุปดีล + บันทึกลง Google Sheet (หรือ CSV ถ้าไม่ตั้งค่า)  
> โหมด **Auto-accept** ให้เนียนที่สุด: บอทจะบันทึกทันทีโดยไม่ถามยืนยัน (ปิด/เปิดได้)

---

## 1) ฟีเจอร์หลัก (MVP)
- รับรูปภาพแคปหน้าจอทาง Telegram
- OCR (ไทย/อังกฤษ) + pre-process ภาพเบื้องต้น
- ตรวจจับค่ามาตรฐาน: `pair`, `side (BUY/SELL)`, `price`, `qty`, `fee`, `time`
- คำนวณแบบ **Average Cost**:
  - เมื่อ **BUY** ➜ ปรับ `avg_cost` และ `position_qty`
  - เมื่อ **SELL** ➜ หักจาก `position_qty` และคำนวณ `realized_pnl`
- บันทึกลง Google Sheet (ถ้าตั้งค่า) หรือ **trades.csv / positions.csv** ในโฟลเดอร์ `data/`
- คำสั่งควบคุม:
  - `/start` – เริ่มใช้งาน
  - `/auto_on` – เปิดบันทึกอัตโนมัติ (ไม่ต้องยืนยัน)
  - `/auto_off` – ปิดบันทึกอัตโนมัติ (ให้ยืนยันก่อน)
  - `/status` – ดูสรุปสั้น ๆ
- รองรับหลายภาษาในข้อความคีย์: ไทย/อังกฤษ

> **หมายเหตุ**: OCR ไม่สมบูรณ์ 100% — แนะนำให้บอทถามยืนยันก่อนบันทึกจริง (โหมด default)  
> ถ้าภาพ/ธีม/ภาษาแตกต่างจากตัวอย่างมาก อาจต้องปรับ pattern เพิ่มในไฟล์ `parser_patterns.yaml`

---

## 2) ติดตั้งอย่างย่อ

### 2.1 เตรียม Python
- Python 3.10+
- ติดตั้ง Tesseract OCR (ถ้าต้องการ OCR แบบออฟไลน์):
  - **Windows**: ดาวน์โหลดจาก https://github.com/UB-Mannheim/tesseract/wiki  
    แล้วจด path ของ `tesseract.exe`
  - **macOS**: `brew install tesseract`
  - **Linux**: `sudo apt-get install tesseract-ocr`
- จากนั้น: `pip install -r requirements.txt`

> ถ้าไม่อยากติดตั้ง Tesseract ให้เปิดใช้ **Google Cloud Vision** แทน (ตั้งค่าใน `.env` และ `config.yaml`).

### 2.2 ตั้งค่า Environment
คัดลอกไฟล์ `.env.example` เป็น `.env` แล้วกรอกค่า:
```
TELEGRAM_BOT_TOKEN=ใส่โทเคนบอทของคุณ
TESSERACT_CMD=ทางเลือก: path ไปยัง tesseract.exe (ถ้าจำเป็นบน Windows)
GOOGLE_SHEETS_JSON=พาธไปยังไฟล์ service account JSON (ถ้าใช้ Google Sheets)
GOOGLE_SHEET_ID=ID ของ Google Sheet (ดูจาก URL)
```

### 2.3 ตั้งค่า Parser
ปรับแก้ไฟล์ `parser_patterns.yaml` เพื่อเพิ่ม/ลด pattern ที่บอทจะจับ เช่น คีย์ไทย/อังกฤษ คำว่า "ราคา/Price", "ปริมาณ/Qty", "ค่าธรรมเนียม/Fee" เป็นต้น

### 2.4 รันบอท
```
python main.py
```
แล้วส่งรูปแคปหน้าจอเข้า Telegram ให้บอทได้เลย

---

## 3) โครงสร้างข้อมูลใน Google Sheet / CSV

### Sheet/CSV: `trades`
| ts_iso | exchange | pair | side | price | qty | fee | fee_asset | gross_value | note | src_image_id |
|-------:|----------|------|------|------:|----:|----:|-----------|------------:|------|---------------|

### Sheet/CSV: `positions`
| pair | position_qty | avg_cost | updated_at |
|------|--------------:|---------:|------------|

### Sheet/CSV: `realized`
| ts_iso | pair | qty | avg_cost_used | sell_price | fee | realized_pnl | note | src_image_id |
|-------:|------|----:|--------------:|-----------:|----:|-------------:|------|---------------|

> คิดเป็น quote asset เสมอ (เช่น USDT)  
> กรณี fee หักเป็นเหรียญอื่น บอทจะบันทึก `fee_asset` เผื่อปรับบัญชีภายหลัง

---

## 4) ขยายความสามารถ
- ระบุ `exchange` อัตโนมัติด้วยโลโก้/คีย์เวิร์ดเฉพาะ (Binance/MEXC/Pionex)
- รองรับ **DCA/GRID bot** สรุปเป็นดีลย่อยภายใต้คำสั่งเดียว
- เชื่อมกับ **Google Drive** เก็บภาพต้นฉบับและลิงก์กลับ
- เพิ่มหน้าเว็บดูกราฟ P&L (Streamlit/FastAPI) — แนบมาเป็นแผนในอนาคต

---

## 5) ปลอดภัยและความเป็นส่วนตัว
- เก็บโทเคน/คีย์ไว้ใน `.env` เท่านั้น
- อย่าส่ง service account JSON ให้บุคคลอื่น
- ถ้าไม่สะดวกใช้ Cloud ให้ใช้ Tesseract แบบออฟไลน์

---

## 6) ปัญหาที่พบบ่อย
- OCR อ่านเลขทศนิยมผิด ➜ ปรับ `image_utils.py` (threshold/resize) หรือแก้ pattern และเปิดโหมดยืนยัน
- จับภาษาไทยไม่แม่น ➜ ใช้ฟอนต์ชัด/โหมด Light, ลองสลับ UI แอปเป็นอังกฤษเวลาแคป
- SELL เกินจำนวนคงเหลือ ➜ ระบบจะตัดเท่าที่มี (ไม่เปิด short)

---

## 7) ใบอนุญาต
MIT License — ใช้/แก้ไขได้อิสระ
