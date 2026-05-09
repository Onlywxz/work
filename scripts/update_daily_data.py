"""Update the daily live hog spot OHLC CSV.

Data source:
    AKShare ``spot_hog_year_trend_soozhu`` interface, which wraps the
    Soozhu live hog data center's year-to-date national hog price series.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPOT_CSV = PROJECT_ROOT / "data" / "spot_daily.csv"
CSV_FIELDS = ["date", "open", "close", "high", "low"]
TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_START_DATE = "2026-01-01"


def today_str() -> str:
    return datetime.now(TIMEZONE).date().isoformat()


def normalize_price(value: float) -> str:
    return f"{float(value):.2f}"


def fetch_spot_prices() -> dict[str, float]:
    spot_df = ak.spot_hog_year_trend_soozhu()
    spot_df["日期"] = spot_df["日期"].astype(str)
    return {row["日期"]: float(row["价格"]) for _, row in spot_df.iterrows()}


def date_range(start_date: str, end_date: str) -> list[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]


def read_existing_rows() -> list[dict[str, str]]:
    if not SPOT_CSV.exists():
        return []

    with SPOT_CSV.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def ensure_csv_header() -> None:
    SPOT_CSV.parent.mkdir(parents=True, exist_ok=True)
    if SPOT_CSV.exists() and SPOT_CSV.stat().st_size > 0:
        return

    with SPOT_CSV.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()


def previous_close(rows: list[dict[str, str]], trade_date: str, fallback: float) -> float:
    previous_rows = [row for row in rows if row.get("date", "") < trade_date and row.get("close")]
    if not previous_rows:
        return fallback

    previous_rows.sort(key=lambda row: row["date"])
    return float(previous_rows[-1]["close"])


def build_ohlc_rows(start_date: str, end_date: str, spot_prices: dict[str, float]) -> tuple[list[dict[str, str]], list[str], list[str]]:
    existing_rows = read_existing_rows()
    source_dates = sorted(date_value for date_value in spot_prices if date_value < start_date)
    if source_dates:
        previous_close_price = spot_prices[source_dates[-1]]
    else:
        previous_close_price = previous_close(existing_rows, start_date, spot_prices.get(start_date, 0))

    output_rows = []
    actual_dates = []
    filled_dates = []
    for trade_date in date_range(start_date, end_date):
        if trade_date in spot_prices:
            close_price = spot_prices[trade_date]
            actual_dates.append(trade_date)
        else:
            close_price = previous_close_price
            filled_dates.append(trade_date)

        open_price = previous_close_price
        output_rows.append(
            {
                "date": trade_date,
                "open": normalize_price(open_price),
                "close": normalize_price(close_price),
                "high": normalize_price(max(open_price, close_price)),
                "low": normalize_price(min(open_price, close_price)),
            }
        )
        previous_close_price = close_price

    return output_rows, actual_dates, filled_dates


def write_spot_rows(rows: list[dict[str, str]]) -> None:
    SPOT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with SPOT_CSV.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def append_today_row(trade_date: str, close_price: float) -> bool:
    ensure_csv_header()
    rows = read_existing_rows()

    if any(row.get("date") == trade_date for row in rows):
        print(f"{trade_date} already exists in {SPOT_CSV}; skip append.")
        return False

    open_price = previous_close(rows, trade_date, close_price)
    high_price = max(open_price, close_price)
    low_price = min(open_price, close_price)

    new_row = {
        "date": trade_date,
        "open": normalize_price(open_price),
        "close": normalize_price(close_price),
        "high": normalize_price(high_price),
        "low": normalize_price(low_price),
    }

    with SPOT_CSV.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writerow(new_row)

    print(f"Appended {trade_date} spot OHLC to {SPOT_CSV}: {new_row}")
    return True


def main() -> None:
    start_date = DEFAULT_START_DATE
    end_date = today_str()
    spot_prices = fetch_spot_prices()
    rows, actual_dates, filled_dates = build_ohlc_rows(start_date, end_date, spot_prices)
    write_spot_rows(rows)
    print(f"Wrote {len(rows)} spot OHLC rows to {SPOT_CSV}: {start_date} to {end_date}.")
    print(f"Actual source dates: {len(actual_dates)}.")
    print(f"Filled dates: {', '.join(filled_dates) if filled_dates else 'none'}.")


if __name__ == "__main__":
    main()
