import os
import csv
import gspread
from google.oauth2.service_account import Credentials
from typing import List, Any
from datetime import datetime, timezone
import yaml

with open("config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEETS_JSON = os.getenv("GOOGLE_SHEETS_JSON")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

def _open_sheet():
    if not (CFG.get("use_google_sheets") and SHEET_ID and SHEETS_JSON and os.path.exists(SHEETS_JSON)):
        return None
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(SHEETS_JSON, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

def _append_csv(path: str, headers: List[str], row: List[Any]):
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(headers)
        w.writerow(row)

class TradeStorage:
    def __init__(self):
        self.sheet = _open_sheet()
        self.trades_name = CFG.get("trades_sheet_name", "trades")
        self.pos_name = CFG.get("positions_sheet_name", "positions")
        self.real_name = CFG.get("realized_sheet_name", "realized")
        if self.sheet:
            import gspread
            for name, headers in [
                (self.trades_name, ["ts_iso","exchange","pair","side","price","qty","fee","fee_asset","gross_value","note","src_image_id"]),
                (self.pos_name, ["pair","position_qty","avg_cost","updated_at"]),
                (self.real_name, ["ts_iso","pair","qty","avg_cost_used","sell_price","fee","realized_pnl","note","src_image_id"]),
            ]:
                try:
                    ws = self.sheet.worksheet(name)
                except gspread.WorksheetNotFound:
                    ws = self.sheet.add_worksheet(title=name, rows=1000, cols=20)
                    ws.append_row(headers)

    def record_trade(self, trade):
        row = [
            trade.get("ts_iso"),
            trade.get("exchange"),
            trade.get("pair"),
            trade.get("side"),
            trade.get("price"),
            trade.get("qty"),
            trade.get("fee"),
            trade.get("fee_asset"),
            (trade.get("price") or 0) * (trade.get("qty") or 0),
            trade.get("note"),
            trade.get("src_image_id"),
        ]
        if self.sheet:
            ws = self.sheet.worksheet(self.trades_name)
            ws.append_row(row)
        else:
            _append_csv(os.path.join(DATA_DIR, "trades.csv"),
                        ["ts_iso","exchange","pair","side","price","qty","fee","fee_asset","gross_value","note","src_image_id"],
                        row)

    def upsert_position(self, pair: str, position_qty: float, avg_cost: float):
        ts = datetime.now(timezone.utc).isoformat()
        if self.sheet:
            ws = self.sheet.worksheet(self.pos_name)
            data = ws.get_all_records()
            found = False
            for idx, rec in enumerate(data, start=2):
                if rec.get("pair") == pair:
                    ws.update(f"B{idx}:D{idx}", [[position_qty, avg_cost, ts]])
                    found = True
                    break
            if not found:
                ws.append_row([pair, position_qty, avg_cost, ts])
        else:
            path = os.path.join(DATA_DIR, "positions.csv")
            rows = []
            if os.path.exists(path):
                with open(path, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
            updated = False
            for r in rows:
                if r["pair"] == pair:
                    r["position_qty"] = str(position_qty)
                    r["avg_cost"] = str(avg_cost)
                    r["updated_at"] = ts
                    updated = True
            if not updated:
                rows.append({"pair": pair, "position_qty": str(position_qty), "avg_cost": str(avg_cost), "updated_at": ts})
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["pair","position_qty","avg_cost","updated_at"])
                w.writeheader()
                for r in rows:
                    w.writerow(r)

    def record_realized(self, pair: str, qty: float, avg_cost_used: float, sell_price: float, fee: float, pnl: float, src_image_id: str, note: str = None):
        ts = datetime.now(timezone.utc).isoformat()
        row = [ts, pair, qty, avg_cost_used, sell_price, fee, pnl, note, src_image_id]
        if self.sheet:
            ws = self.sheet.worksheet(self.real_name)
            ws.append_row(row)
        else:
            _append_csv(os.path.join(DATA_DIR, "realized.csv"),
                        ["ts_iso","pair","qty","avg_cost_used","sell_price","fee","realized_pnl","note","src_image_id"],
                        row)

    def get_position(self, pair: str):
        if self.sheet:
            ws = self.sheet.worksheet(self.pos_name)
            data = ws.get_all_records()
            for rec in data:
                if rec.get("pair") == pair:
                    return {
                        "pair": pair,
                        "position_qty": float(rec.get("position_qty") or 0),
                        "avg_cost": float(rec.get("avg_cost") or 0),
                    }
            return {"pair": pair, "position_qty": 0.0, "avg_cost": 0.0}
        else:
            path = os.path.join(DATA_DIR, "positions.csv")
            if not os.path.exists(path):
                return {"pair": pair, "position_qty": 0.0, "avg_cost": 0.0}
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for rec in reader:
                    if rec.get("pair") == pair:
                        return {
                            "pair": pair,
                            "position_qty": float(rec.get("position_qty") or 0),
                            "avg_cost": float(rec.get("avg_cost") or 0),
                        }
            return {"pair": pair, "position_qty": 0.0, "avg_cost": 0.0}

    def get_all_positions(self):
        if self.sheet:
            ws = self.sheet.worksheet(self.pos_name)
            data = ws.get_all_records()
            return data
        else:
            path = os.path.join(DATA_DIR, "positions.csv")
            if not os.path.exists(path):
                return []
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return list(reader)
