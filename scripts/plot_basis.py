"""Update DCE live hog futures data, calculate basis, and plot basis lines."""

from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / "reports" / ".matplotlib-cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


FUTURES_CSV = PROJECT_ROOT / "data" / "dce_hog_futures_daily.csv"
SPOT_CSV = PROJECT_ROOT / "data" / "spot_daily.csv"
BASIS_CSV = PROJECT_ROOT / "data" / "basis_daily.csv"
BASIS_CHART = PROJECT_ROOT / "reports" / "basis_by_contract.png"
BASIS_WEB_CHART = PROJECT_ROOT / "web" / "assets" / "basis_latest.png"
TIMEZONE = ZoneInfo("Asia/Shanghai")

FUTURES_FIELDS = ["date", "contract", "close"]
BASIS_FIELDS = ["date", "contract", "spot_close", "futures_close", "basis"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch DCE live hog futures closes, calculate basis, and plot basis lines."
    )
    parser.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD or YYYYMMDD format. Defaults to today in Asia/Shanghai.",
    )
    parser.add_argument(
        "--start-date",
        default="2026-01-01",
        help="Start date for historical DCE live hog futures backfill.",
    )
    parser.add_argument(
        "--end-date",
        help="End date for historical DCE live hog futures backfill. Defaults to today.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=14,
        help="Days to look back when the target date is not a DCE trading day.",
    )
    parser.add_argument(
        "--chart",
        default=str(BASIS_CHART),
        help="Output path for the basis line chart.",
    )
    parser.add_argument(
        "--web-chart",
        default=str(BASIS_WEB_CHART),
        help="Output path for the web-readable latest basis chart.",
    )
    return parser.parse_args()


def today_str() -> str:
    return datetime.now(TIMEZONE).date().isoformat()


def normalize_date(value: str) -> str:
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    datetime.strptime(value, "%Y-%m-%d")
    return value


def dce_date(value: str) -> str:
    return value.replace("-", "")


def contract_year(value: str) -> int:
    return int(value[:4])


def format_price(value: float) -> str:
    return f"{float(value):.2f}"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []

    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fetch_hog_futures_for_date(trade_date: str) -> list[dict[str, str]]:
    try:
        daily_df = ak.get_dce_daily(dce_date(trade_date))
    except Exception as exc:
        print(f"DCE fetch failed for {trade_date}: {exc}")
        return fetch_hog_futures_from_sina(trade_date)

    if daily_df.empty:
        return fetch_hog_futures_from_sina(trade_date)

    hog_df = daily_df[
        daily_df["symbol"].astype(str).str.lower().str.startswith("lh")
        | (daily_df["variety"].astype(str).str.upper() == "LH")
    ].copy()
    hog_df = hog_df[hog_df["close"].notna()]

    rows = []
    for _, row in hog_df.iterrows():
        rows.append(
            {
                "date": trade_date,
                "contract": str(row["symbol"]).upper(),
                "close": format_price(row["close"]),
            }
        )
    return sorted(rows, key=lambda item: item["contract"])


def candidate_hog_contracts(trade_date: str) -> list[str]:
    year = contract_year(trade_date)
    months = [1, 3, 5, 7, 9, 11]
    return [
        f"LH{target_year % 100:02d}{month:02d}"
        for target_year in range(year - 1, year + 3)
        for month in months
    ]


def candidate_hog_contracts_for_range(start_date: str, end_date: str) -> list[str]:
    start_year = contract_year(start_date) - 1
    end_year = contract_year(end_date) + 2
    months = [1, 3, 5, 7, 9, 11]
    return [
        f"LH{target_year % 100:02d}{month:02d}"
        for target_year in range(start_year, end_year + 1)
        for month in months
    ]


def parse_sina_contract_name(value: str) -> str:
    digits = "".join(char for char in value if char.isdigit())
    if len(digits) >= 4:
        return f"LH{digits[-4:]}"
    return value.upper()


def discover_sina_hog_contracts(trade_date: str) -> list[str]:
    candidates = candidate_hog_contracts(trade_date)
    try:
        spot_df = ak.futures_zh_spot(symbol=",".join(candidates), market="CF", adjust="0")
    except Exception as exc:
        print(f"Sina futures contract discovery failed for {trade_date}: {exc}")
        return candidates

    if spot_df.empty or "symbol" not in spot_df.columns:
        return candidates

    contracts = sorted({parse_sina_contract_name(str(symbol)) for symbol in spot_df["symbol"]})
    return contracts or candidates


def fetch_hog_futures_from_sina(trade_date: str) -> list[dict[str, str]]:
    rows = []
    for contract in discover_sina_hog_contracts(trade_date):
        try:
            daily_df = ak.futures_zh_daily_sina(symbol=contract)
        except Exception as exc:
            print(f"Sina daily fetch failed for {contract}: {exc}")
            continue

        if daily_df.empty:
            continue

        daily_df["date"] = daily_df["date"].astype(str)
        matched_rows = daily_df[daily_df["date"] == trade_date]
        if matched_rows.empty:
            continue

        close_price = matched_rows.iloc[-1]["close"]
        rows.append(
            {
                "date": trade_date,
                "contract": contract,
                "close": format_price(close_price),
            }
        )

    if rows:
        print(f"Used Sina futures daily bars for DCE live hog contracts on {trade_date}.")
    return sorted(rows, key=lambda item: item["contract"])


def fetch_hog_futures_history(start_date: str, end_date: str) -> list[dict[str, str]]:
    rows = []
    for contract in candidate_hog_contracts_for_range(start_date, end_date):
        try:
            daily_df = ak.futures_zh_daily_sina(symbol=contract)
        except Exception as exc:
            print(f"Sina daily fetch failed for {contract}: {exc}")
            continue

        if daily_df.empty:
            continue

        daily_df["date"] = daily_df["date"].astype(str)
        matched_df = daily_df[(daily_df["date"] >= start_date) & (daily_df["date"] <= end_date)]
        if matched_df.empty:
            continue

        for _, row in matched_df.iterrows():
            rows.append(
                {
                    "date": str(row["date"]),
                    "contract": contract,
                    "close": format_price(row["close"]),
                }
            )

        print(
            f"Fetched {len(matched_df)} rows for {contract}: "
            f"{matched_df['date'].min()} to {matched_df['date'].max()}."
        )

    return sorted(rows, key=lambda item: (item["date"], item["contract"]))


def fetch_latest_hog_futures(target_date: str, lookback_days: int) -> list[dict[str, str]]:
    start_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    for offset in range(lookback_days + 1):
        trade_date = (start_date - timedelta(days=offset)).isoformat()
        rows = fetch_hog_futures_for_date(trade_date)
        if rows:
            if trade_date != target_date:
                print(f"No DCE hog data for {target_date}; using latest available date {trade_date}.")
            return rows

    raise RuntimeError(
        f"No DCE live hog futures data found from {target_date} back {lookback_days} days."
    )


def upsert_futures_rows(new_rows: list[dict[str, str]]) -> None:
    rows_by_key = {
        (row.get("date", ""), row.get("contract", "")): {
            "date": row.get("date", ""),
            "contract": row.get("contract", ""),
            "close": format_price(row.get("close", 0) or 0),
        }
        for row in read_csv_rows(FUTURES_CSV)
        if row.get("date") and row.get("contract")
    }

    for row in new_rows:
        rows_by_key[(row["date"], row["contract"])] = row

    output_rows = sorted(rows_by_key.values(), key=lambda item: (item["date"], item["contract"]))
    write_csv_rows(FUTURES_CSV, FUTURES_FIELDS, output_rows)
    print(f"Wrote {len(output_rows)} rows to {FUTURES_CSV}.")


def write_futures_rows(rows: list[dict[str, str]]) -> None:
    rows_by_key = {
        (row["date"], row["contract"]): {
            "date": row["date"],
            "contract": row["contract"],
            "close": format_price(row["close"]),
        }
        for row in rows
        if row.get("date") and row.get("contract") and row.get("close")
    }
    output_rows = sorted(rows_by_key.values(), key=lambda item: (item["date"], item["contract"]))
    write_csv_rows(FUTURES_CSV, FUTURES_FIELDS, output_rows)
    print(f"Wrote {len(output_rows)} rows to {FUTURES_CSV}.")


def calculate_basis_rows() -> list[dict[str, str]]:
    spot_by_date = {
        row["date"]: float(row["close"])
        for row in read_csv_rows(SPOT_CSV)
        if row.get("date") and row.get("close")
    }
    futures_rows = read_csv_rows(FUTURES_CSV)

    basis_rows = []
    for row in futures_rows:
        trade_date = row.get("date", "")
        if trade_date not in spot_by_date:
            continue

        spot_close = spot_by_date[trade_date] * 1000
        futures_close = float(row["close"])
        basis = spot_close - futures_close
        basis_rows.append(
            {
                "date": trade_date,
                "contract": row["contract"],
                "spot_close": format_price(spot_close),
                "futures_close": format_price(futures_close),
                "basis": format_price(basis),
            }
        )

    return sorted(basis_rows, key=lambda item: (item["date"], item["contract"]))


def write_basis_csv() -> list[dict[str, str]]:
    basis_rows = calculate_basis_rows()
    write_csv_rows(BASIS_CSV, BASIS_FIELDS, basis_rows)
    print(f"Wrote {len(basis_rows)} rows to {BASIS_CSV}.")
    return basis_rows


def plot_basis(chart_path: Path) -> None:
    basis_rows = read_csv_rows(BASIS_CSV)
    chart_path.parent.mkdir(parents=True, exist_ok=True)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(12, 6), dpi=160)
    fig.patch.set_facecolor("#f7f9fb")
    ax.set_facecolor("#ffffff")

    if not basis_rows:
        ax.text(
            0.5,
            0.5,
            "No basis data",
            ha="center",
            va="center",
            fontsize=16,
            color="#64748b",
            transform=ax.transAxes,
        )
    else:
        contracts = sorted({row["contract"] for row in basis_rows})
        color_map = plt.get_cmap("tab10")
        for index, contract in enumerate(contracts):
            contract_rows = [row for row in basis_rows if row["contract"] == contract]
            contract_rows.sort(key=lambda item: item["date"])
            dates = [datetime.strptime(row["date"], "%Y-%m-%d") for row in contract_rows]
            values = [float(row["basis"]) for row in contract_rows]
            ax.plot(
                dates,
                values,
                marker="o",
                linewidth=2.2,
                markersize=4,
                color=color_map(index % 10),
                label=contract,
            )

        ax.legend(loc="best", frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")

    ax.set_title("DCE Live Hog Futures Basis by Contract", fontsize=15, pad=14)
    ax.set_xlabel("Date")
    ax.set_ylabel("Basis")
    ax.axhline(0, color="#334155", linewidth=1, alpha=0.75)
    ax.grid(True, color="#e2e8f0", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote basis chart to {chart_path}.")


def main() -> None:
    args = parse_args()
    if args.date:
        target_date = normalize_date(args.date)
        futures_rows = fetch_latest_hog_futures(target_date, args.lookback_days)
        upsert_futures_rows(futures_rows)
    else:
        start_date = normalize_date(args.start_date)
        end_date = normalize_date(args.end_date) if args.end_date else today_str()
        futures_rows = fetch_hog_futures_history(start_date, end_date)
        if not futures_rows:
            raise RuntimeError(f"No DCE live hog futures history found from {start_date} to {end_date}.")
        write_futures_rows(futures_rows)

    write_basis_csv()
    chart_path = Path(args.chart).expanduser().resolve()
    web_chart_path = Path(args.web_chart).expanduser().resolve()
    plot_basis(chart_path)
    if web_chart_path != chart_path:
        plot_basis(web_chart_path)


if __name__ == "__main__":
    main()
