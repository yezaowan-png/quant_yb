"""Daily limit-up/limit-down board backed by Tushare limit_list_d."""

from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
from typing import Any

import pandas as pd

from data.stock_pool import save_stock_pool
from data.tushare_client import TushareClient
from visual.components import html_document, stock_link_html


LIMIT_FIELDS = ",".join(
    [
        "trade_date",
        "ts_code",
        "industry",
        "name",
        "close",
        "pct_chg",
        "swing",
        "amount",
        "limit_amount",
        "float_mv",
        "total_mv",
        "turnover_ratio",
        "fd_amount",
        "first_time",
        "last_time",
        "open_times",
        "up_stat",
        "limit_times",
        "limit",
        "exchange",
        "pe",
    ]
)


@dataclass
class LimitBoardResult:
    trade_date: str
    detail_path: Path
    industry_path: Path
    concept_path: Path
    html_path: Path
    pool_path: Path | None
    detail: pd.DataFrame
    industry: pd.DataFrame
    concepts: pd.DataFrame


def _stats_dir(config: dict) -> Path:
    return Path(config["output"].get("statistics_dir", "output/statistics"))


def _call_tushare(config: dict, symbol: str, api_name: str, callback):
    client = TushareClient.from_config(config)
    return client.call(symbol, api_name, callback)


def fetch_limit_detail(config: dict, trade_date: str, pro: Any | None = None) -> pd.DataFrame:
    trade_date = str(trade_date).replace("-", "")
    if pro is not None:
        try:
            df = pro.limit_list_d(trade_date=trade_date, fields=LIMIT_FIELDS)
        except TypeError:
            df = pro.limit_list_d(trade_date=trade_date)
    else:
        df = _call_tushare(
            config,
            trade_date,
            "limit_list_d",
            lambda api: api.limit_list_d(trade_date=trade_date, fields=LIMIT_FIELDS),
        )
    return clean_limit_detail(df)


def fetch_limit_concepts(config: dict, trade_date: str, pro: Any | None = None) -> pd.DataFrame:
    trade_date = str(trade_date).replace("-", "")
    try:
        if pro is not None:
            df = pro.limit_cpt_list(trade_date=trade_date)
        else:
            df = _call_tushare(
                config,
                trade_date,
                "limit_cpt_list",
                lambda api: api.limit_cpt_list(trade_date=trade_date),
            )
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"])
    result = df.copy()
    for col in ("trade_date", "ts_code", "name", "up_stat", "rank"):
        if col in result.columns:
            result[col] = result[col].astype(str)
    for col in ("days", "cons_nums", "up_nums", "pct_chg"):
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    return result


def clean_limit_detail(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        columns = LIMIT_FIELDS.split(",")
        if "limit_type" not in columns:
            columns.append("limit_type")
        return pd.DataFrame(columns=columns)
    result = df.copy()
    if "limit_type" not in result.columns and "limit" in result.columns:
        result["limit_type"] = result["limit"]
    for col in ("trade_date", "ts_code", "industry", "name", "first_time", "last_time", "up_stat", "limit_type", "exchange"):
        if col in result.columns:
            result[col] = result[col].astype(str)
    for col in result.columns:
        if col not in {"trade_date", "ts_code", "industry", "name", "first_time", "last_time", "up_stat", "limit_type", "exchange"}:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    if "limit_type" not in result.columns:
        result["limit_type"] = ""
    return result.sort_values(["limit_type", "limit_times", "pct_chg"], ascending=[False, False, False]).reset_index(drop=True)


def build_industry_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(
            columns=["industry", "limit_up", "limit_down", "opened", "avg_turnover", "avg_pe", "avg_total_mv", "leaders"]
        )
    work = detail.copy()
    work["industry"] = work.get("industry", "").fillna("未分类").replace("", "未分类")
    rows = []
    for industry, group in work.groupby("industry", dropna=False):
        up = group[group["limit_type"] == "U"]
        down = group[group["limit_type"] == "D"]
        opened = group[group["limit_type"] == "Z"]
        leaders = up.sort_values(["limit_times", "fd_amount"], ascending=False).head(5)
        rows.append(
            {
                "industry": industry,
                "limit_up": int(len(up)),
                "limit_down": int(len(down)),
                "opened": int(len(opened)),
                "avg_turnover": round(float(pd.to_numeric(up.get("turnover_ratio"), errors="coerce").mean()), 2)
                if len(up)
                else None,
                "avg_pe": round(float(pd.to_numeric(up.get("pe"), errors="coerce").mean()), 2)
                if len(up)
                else None,
                "avg_total_mv": round(float(pd.to_numeric(up.get("total_mv"), errors="coerce").mean()), 2)
                if len(up)
                else None,
                "leaders": ", ".join(
                    f"{row.get('name', '')}({row.get('ts_code', '')})" for _, row in leaders.iterrows()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["limit_up", "opened"], ascending=False).reset_index(drop=True)


def classify_limit_pools(
    config: dict,
    detail: pd.DataFrame,
    trade_date: str,
    prefix: str = "涨跌停",
    include_industry: bool = True,
) -> Path | None:
    if detail.empty:
        return None
    pools: list[tuple[str, pd.DataFrame, str]] = [
        (f"{prefix}_涨停_{trade_date}", detail[detail["limit_type"] == "U"], "当日涨停股票"),
        (f"{prefix}_跌停_{trade_date}", detail[detail["limit_type"] == "D"], "当日跌停股票"),
        (f"{prefix}_炸板_{trade_date}", detail[detail["limit_type"] == "Z"], "当日炸板股票"),
    ]
    if include_industry:
        for industry, group in detail[detail["limit_type"] == "U"].groupby("industry", dropna=False):
            label = str(industry or "未分类").replace("/", "_").replace(",", "_")
            pools.append((f"{prefix}_{label}_{trade_date}", group, f"{trade_date} 涨停行业分类: {label}"))

    last_path = None
    for name, group, description in pools:
        if group.empty:
            continue
        stocks = [
            {"ts_code": row.get("ts_code", ""), "name": row.get("name", "")}
            for _, row in group.iterrows()
        ]
        last_path = save_stock_pool(config, name, stocks, description=description, merge=False)
    return last_path


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "--"


def _table(df: pd.DataFrame, output_path: Path, config: dict | None = None, limit: int = 100) -> str:
    if df.empty:
        return '<p class="empty">暂无数据</p>'
    header = "".join(f"<th>{html.escape(str(col))}</th>" for col in df.columns)
    rows = []
    for _, row in df.head(limit).iterrows():
        cells = []
        for column, value in row.items():
            if column == "ts_code" and not pd.isna(value):
                cells.append(f"<td>{stock_link_html(config, output_path, value)}</td>")
            else:
                cells.append(f"<td>{html.escape('' if pd.isna(value) else str(value))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _write_report(
    trade_date: str,
    detail: pd.DataFrame,
    industry: pd.DataFrame,
    concepts: pd.DataFrame,
    output_path: Path,
    config: dict | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    up = detail[detail["limit_type"] == "U"]
    down = detail[detail["limit_type"] == "D"]
    opened = detail[detail["limit_type"] == "Z"]
    cards = [
        ("涨停", len(up)),
        ("跌停", len(down)),
        ("炸板", len(opened)),
        ("最高连板", int(pd.to_numeric(up.get("limit_times"), errors="coerce").max()) if len(up) else 0),
    ]
    card_html = "".join(f"<div><span>{label}</span><strong>{value}</strong></div>" for label, value in cards)
    top_up = up.sort_values(["limit_times", "fd_amount"], ascending=False)
    output_path.write_text(
        html_document(
            title=f"{trade_date} 涨跌停看板",
            styles="""
            body { margin: 0; background: #f4f6fa; color: #1f2937; font-family: "Microsoft YaHei", "Noto Sans SC", sans-serif; }
            main { width: min(1380px, calc(100vw - 40px)); margin: 0 auto; padding: 28px 0 44px; }
            h1 { margin: 0 0 16px; font-size: 28px; }
            h2 { margin: 24px 0 10px; font-size: 18px; }
            .cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
            .cards div { background: white; border: 1px solid #d9e2ef; border-radius: 8px; padding: 14px; }
            .cards span { display: block; color: #667085; font-size: 12px; }
            .cards strong { font-size: 26px; }
            table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #d9e2ef; }
            th, td { padding: 8px 10px; border-bottom: 1px solid #e6edf5; text-align: left; font-size: 13px; vertical-align: top; }
            th { background: #eef4ff; }
            a.stock-link { color: #2454a6; font-weight: 700; text-decoration: none; }
            a.stock-link:hover { text-decoration: underline; }
            .empty { background: white; border: 1px solid #d9e2ef; padding: 18px; }
            """,
            body=f"""
            <main>
              <h1>{html.escape(trade_date)} 涨跌停看板</h1>
              <section class="cards">{card_html}</section>
              <h2>涨停龙头与基本面</h2>
              {_table(top_up[[
                  col for col in [
                      "ts_code", "name", "industry", "close", "pct_chg", "limit_times",
                      "up_stat", "turnover_ratio", "pe", "float_mv", "total_mv",
                      "first_time", "last_time", "open_times"
                  ] if col in top_up.columns
              ]], output_path, config)}
              <h2>行业分类</h2>
              {_table(industry, output_path, config)}
              <h2>强势概念</h2>
              {_table(concepts, output_path, config)}
            </main>
            """,
        ),
        encoding="utf-8",
    )
    return output_path


def save_limit_board(
    config: dict,
    trade_date: str,
    pro: Any | None = None,
    save_pools: bool = False,
    pool_prefix: str = "涨跌停",
) -> LimitBoardResult:
    trade_date = str(trade_date).replace("-", "")
    stats_dir = _stats_dir(config)
    stats_dir.mkdir(parents=True, exist_ok=True)
    detail = fetch_limit_detail(config, trade_date, pro=pro)
    concepts = fetch_limit_concepts(config, trade_date, pro=pro)
    industry = build_industry_summary(detail)
    detail_path = stats_dir / f"limit_board_{trade_date}.csv"
    industry_path = stats_dir / f"limit_board_{trade_date}_industry.csv"
    concept_path = stats_dir / f"limit_board_{trade_date}_concepts.csv"
    html_path = stats_dir / f"limit_board_{trade_date}.html"
    detail.to_csv(detail_path, index=False)
    industry.to_csv(industry_path, index=False)
    concepts.to_csv(concept_path, index=False)
    _write_report(trade_date, detail, industry, concepts, html_path, config)
    pool_path = classify_limit_pools(config, detail, trade_date, prefix=pool_prefix) if save_pools else None
    return LimitBoardResult(trade_date, detail_path, industry_path, concept_path, html_path, pool_path, detail, industry, concepts)
