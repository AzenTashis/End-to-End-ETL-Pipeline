"""
Business dashboard built with Matplotlib, from data in PostgreSQL.

    python -m analytics.dashboard

Creates PNG files in analytics/output/:
    monthly_revenue.png, revenue_by_category.png, sales_by_region.png,
    top_products.png, transaction_volume.png, data_quality_summary.png,
    dashboard.png (all charts on one page)

This is kept separate from the ETL code on purpose: the pipeline's job is to
produce trustworthy tables; charts are one of many things built on top.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files, no window needed (works inside Docker too)
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "analytics" / "output"

# Colours: one blue for single-series charts, blue + orange when comparing two series.
BLUE = "#2a78d6"
ORANGE = "#eb6834"
INK = "#0b0b0b"
MUTED = "#898781"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _inr(value: float, _pos=None) -> str:
    """Format rupees the Indian way: 1.2 Cr, 3.4 L, 5.6 K."""
    if abs(value) >= 1e7:
        return f"₹{value / 1e7:.1f} Cr"
    if abs(value) >= 1e5:
        return f"₹{value / 1e5:.1f} L"
    if abs(value) >= 1e3:
        return f"₹{value / 1e3:.0f} K"
    return f"₹{value:.0f}"


def _style(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=10)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _month_labels(df: pd.DataFrame) -> list[str]:
    return [f"{MONTHS[int(m) - 1]} {str(int(y))[2:]}" for y, m in zip(df["transaction_year"], df["transaction_month"])]


def plot_monthly_revenue(ax, df: pd.DataFrame) -> None:
    labels = _month_labels(df)
    ax.plot(labels, df["revenue"], color=BLUE, linewidth=2, marker="o", markersize=4)
    _style(ax, "Monthly revenue (after discounts)")
    ax.yaxis.set_major_formatter(FuncFormatter(_inr))
    ax.set_ylim(bottom=0)
    ax.set_xticks(range(0, len(labels), max(1, len(labels) // 8)))
    peak = df["revenue"].idxmax()
    ax.annotate(_inr(df.loc[peak, "revenue"]), (labels[peak], df.loc[peak, "revenue"]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, color=INK)


def _hbar(ax, names, values, title, formatter=_inr) -> None:
    names, values = list(names)[::-1], list(values)[::-1]   # biggest on top
    bars = ax.barh(names, values, color=BLUE, height=0.6)
    _style(ax, title)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.xaxis.set_major_formatter(FuncFormatter(formatter))
    for bar, value in zip(bars, values):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, "  " + formatter(value),
                va="center", fontsize=8, color=INK)
    ax.set_xlim(0, max(values) * 1.25 if values else 1)


def plot_revenue_by_category(ax, df: pd.DataFrame) -> None:
    _hbar(ax, df["category"], df["revenue"], "Revenue by category")


def plot_sales_by_region(ax, df: pd.DataFrame) -> None:
    _hbar(ax, df["region"], df["revenue"], "Revenue by region")


def plot_top_products(ax, df: pd.DataFrame) -> None:
    names = [n if len(n) <= 26 else n[:24] + "…" for n in df["product_name"]]
    _hbar(ax, names, df["units_sold"], "Top 10 products by units sold", formatter=lambda v, _p=None: f"{v:,.0f}")


def plot_transaction_volume(ax, df: pd.DataFrame) -> None:
    labels = _month_labels(df)
    ax.bar(labels, df["transactions"], color=BLUE, width=0.7)
    _style(ax, "Transactions per month")
    ax.set_xticks(range(0, len(labels), max(1, len(labels) // 8)))


def plot_quality_summary(ax, report: dict | None) -> None:
    """Raw vs clean: how much variety (mess) the cleaning removed."""
    _style(ax, "Data quality: raw vs clean")
    if not report or not report.get("raw_vs_clean"):
        ax.text(0.5, 0.5, "No data quality report found", ha="center", va="center", color=MUTED)
        ax.set_xticks([])
        ax.set_yticks([])
        return
    comparison = {k: v for k, v in report["raw_vs_clean"].items() if k != "rows"}
    labels = [k.replace("distinct_", "").replace("_spellings", "").capitalize() for k in comparison]
    raw = [v[0] for v in comparison.values()]
    clean = [v[1] for v in comparison.values()]
    positions = range(len(labels))
    width = 0.38
    raw_bars = ax.bar([p - width / 2 - 0.01 for p in positions], raw, width, color=ORANGE, label="Raw files")
    clean_bars = ax.bar([p + width / 2 + 0.01 for p in positions], clean, width, color=BLUE, label="After cleaning")
    ax.set_xticks(list(positions))
    ax.set_xticklabels([f"{label}\nspellings" for label in labels])
    for bars in (raw_bars, clean_bars):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{bar.get_height():.0f}",
                    ha="center", va="bottom", fontsize=8, color=INK)
    rows_raw, rows_clean = report["raw_vs_clean"]["rows"]
    ax.set_ylim(0, max(raw + clean) * 1.4)   # leave headroom so the legend never covers a bar
    ax.legend(frameon=False, fontsize=8, loc="upper left", ncol=2,
              title=f"Rows: {rows_raw:,} raw → {rows_clean:,} clean", title_fontsize=8)


CHARTS = [
    ("monthly_revenue", plot_monthly_revenue, "monthly_revenue"),
    ("revenue_by_category", plot_revenue_by_category, "revenue_by_category"),
    ("sales_by_region", plot_sales_by_region, "sales_by_region"),
    ("top_products", plot_top_products, "top_10_products"),
    ("transaction_volume", plot_transaction_volume, "monthly_transaction_volume"),
]


def build_dashboard(data: dict[str, pd.DataFrame], quality_report: dict | None, output_dir: Path) -> list[Path]:
    """Save one PNG per chart plus a combined dashboard.png. Returns the file paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 9, "figure.facecolor": SURFACE})
    written = []

    for file_name, plotter, query_name in CHARTS:
        fig, ax = plt.subplots(figsize=(8, 4.2))
        plotter(ax, data[query_name])
        fig.tight_layout()
        path = output_dir / f"{file_name}.png"
        fig.savefig(path, dpi=130)
        plt.close(fig)
        written.append(path)

    fig, ax = plt.subplots(figsize=(8, 4.2))
    plot_quality_summary(ax, quality_report)
    fig.tight_layout()
    path = output_dir / "data_quality_summary.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    written.append(path)

    fig, axes = plt.subplots(3, 2, figsize=(15, 13))
    fig.suptitle("Meridian Retail: sales dashboard", x=0.02, ha="left", fontsize=16, color=INK)
    for ax, (_, plotter, query_name) in zip(axes.flat, CHARTS):
        plotter(ax, data[query_name])
    plot_quality_summary(axes.flat[5], quality_report)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    path = output_dir / "dashboard.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    written.append(path)
    return written


def latest_quality_report(reports_dir: Path) -> dict | None:
    files = sorted(reports_dir.glob("*/data_quality_report.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def main() -> None:
    from analytics.run_queries import load_queries, run_query
    from config.config import get_settings
    from src.loading.database import get_engine

    queries = load_queries()
    engine = get_engine()
    data = {query_name: run_query(engine, queries[query_name]) for _, _, query_name in CHARTS}
    engine.dispose()
    report = latest_quality_report(get_settings().reports_dir)
    for path in build_dashboard(data, report, OUTPUT_DIR):
        print(f"Saved {path}")


if __name__ == "__main__":
    main()
