"""Backfill dashboard seed JSON and generate the latest basis chart asset."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPOT_CSV = PROJECT_ROOT / "data" / "spot_daily.csv"
BASIS_CSV = PROJECT_ROOT / "data" / "basis_daily.csv"
BASIS_IMAGE = PROJECT_ROOT / "web" / "assets" / "basis_latest.png"

os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / "reports" / ".matplotlib-cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


SEED_DATA_RE = re.compile(
    r'(<script\s+id=["\']seed-data["\']\s+type=["\']application/json["\']\s*>)(.*?)(</script>)',
    re.IGNORECASE | re.DOTALL,
)

SPOT_KEYS = ("spotDaily", "spot_daily", "spotOhlc", "spot_ohlc", "ohlc", "candles")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update dashboard seed-data JSON from CSV files and generate basis_latest.png."
    )
    parser.add_argument(
        "--html",
        help="HTML file to update. Defaults to the first HTML file found in the project root.",
    )
    parser.add_argument(
        "--basis-image",
        default=str(BASIS_IMAGE),
        help="Output path for the latest basis chart image.",
    )
    return parser.parse_args()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []

    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def latest_row(rows: list[dict[str, str]]) -> dict[str, str]:
    dated_rows = [row for row in rows if row.get("date")]
    if not dated_rows:
        raise RuntimeError("spot_daily.csv 中没有可用现货数据。")
    return sorted(dated_rows, key=lambda row: row["date"])[-1]


def latest_basis_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    dated_rows = [row for row in rows if row.get("date")]
    if not dated_rows:
        return []

    latest_date = max(row["date"] for row in dated_rows)
    return sorted(
        [row for row in dated_rows if row["date"] == latest_date],
        key=lambda row: row.get("contract", ""),
    )


def spot_record(row: dict[str, str]) -> dict[str, float | str]:
    return {
        "date": row["date"],
        "open": float(row["open"]),
        "close": float(row["close"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
    }


def update_list_by_date(rows: list[Any], record: dict[str, float | str]) -> bool:
    if not all(isinstance(item, dict) for item in rows):
        return False

    if rows and not any(key in rows[0] for key in ("date", "x", "time")):
        return False

    target_date = str(record["date"])
    for index, item in enumerate(rows):
        item_date = str(item.get("date") or item.get("x") or item.get("time") or "")
        if item_date == target_date:
            updated = dict(item)
            updated.update(record)
            rows[index] = updated
            return True

    rows.append(record)
    rows.sort(key=lambda item: str(item.get("date") or item.get("x") or item.get("time") or ""))
    return True


def recursively_update_spot(data: Any, record: dict[str, float | str]) -> bool:
    updated = False
    if isinstance(data, dict):
        for key in SPOT_KEYS:
            if isinstance(data.get(key), list):
                updated = update_list_by_date(data[key], record) or updated

        for value in data.values():
            updated = recursively_update_spot(value, record) or updated
    elif isinstance(data, list):
        has_ohlc_shape = all(field in data[0] for field in ("open", "close", "high", "low")) if data else False
        if has_ohlc_shape:
            updated = update_list_by_date(data, record) or updated
        else:
            for value in data:
                updated = recursively_update_spot(value, record) or updated

    return updated


def update_seed_json(html_text: str, record: dict[str, float | str]) -> tuple[str, bool]:
    match = SEED_DATA_RE.search(html_text)
    if not match:
        raise RuntimeError('HTML 中未找到 <script id="seed-data" type="application/json">。</script>')

    seed_data = json.loads(match.group(2).strip())
    updated = recursively_update_spot(seed_data, record)
    if not updated:
        if not isinstance(seed_data, dict):
            raise RuntimeError("seed-data JSON 不是对象，且未找到可回填的 OHLC 数组。")
        seed_data["spotDaily"] = [record]
        updated = True

    new_json = json.dumps(seed_data, ensure_ascii=False, indent=2)
    new_script = f"{match.group(1)}\n{new_json}\n{match.group(3)}"
    return html_text[: match.start()] + new_script + html_text[match.end() :], updated


def find_html_file() -> Path:
    candidates = sorted(PROJECT_ROOT.glob("*.html"))
    if not candidates:
        raise FileNotFoundError("项目根目录没有找到 HTML 文件；请先把原 HTML 放回当前目录。")
    return candidates[0]


def plot_latest_basis(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(12, 6), dpi=160)
    fig.patch.set_facecolor("#f7f9fb")
    ax.set_facecolor("#ffffff")

    if not rows:
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
        contracts = sorted({row["contract"] for row in rows})
        color_map = plt.get_cmap("tab10")
        for index, contract in enumerate(contracts):
            contract_rows = [row for row in rows if row["contract"] == contract]
            contract_rows.sort(key=lambda item: item["date"])
            dates = [datetime.strptime(row["date"], "%Y-%m-%d") for row in contract_rows]
            values = [float(row["basis"]) for row in contract_rows]
            ax.plot(
                dates,
                values,
                marker="o",
                linewidth=2.2,
                markersize=5,
                color=color_map(index % 10),
                label=contract,
            )
        ax.legend(loc="best", frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")

    ax.set_title("Latest DCE Live Hog Basis", fontsize=15, pad=14)
    ax.set_xlabel("Date")
    ax.set_ylabel("Basis")
    ax.axhline(0, color="#334155", linewidth=1, alpha=0.75)
    ax.grid(True, color="#e2e8f0", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    basis_image = Path(args.basis_image).expanduser().resolve()

    latest_spot = spot_record(latest_row(read_csv_rows(SPOT_CSV)))
    latest_basis = latest_basis_rows(read_csv_rows(BASIS_CSV))
    plot_latest_basis(latest_basis, basis_image)

    html_path = Path(args.html).expanduser().resolve() if args.html else find_html_file()

    html_text = html_path.read_text(encoding="utf-8")
    updated_html, _ = update_seed_json(html_text, latest_spot)
    html_path.write_text(updated_html, encoding="utf-8")

    print(f"Updated seed-data in {html_path} with spot row {latest_spot['date']}.")
    print(f"Wrote latest basis chart to {basis_image}.")


if __name__ == "__main__":
    main()
