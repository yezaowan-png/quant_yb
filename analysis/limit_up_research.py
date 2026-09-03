"""Recent limit-up stock research, fine theme classification, and pool export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from analysis.limit_moves import LIMIT_FIELDS, clean_limit_detail
from data.stock_pool import save_stock_pool
from data.tushare_client import TushareClient


@dataclass(frozen=True)
class FineTheme:
    name: str
    description: str
    concept_codes: tuple[str, ...] = ()
    industry_keywords: tuple[str, ...] = ()
    name_keywords: tuple[str, ...] = ()
    seed_symbols: tuple[str, ...] = ()
    priority: int = 100


@dataclass
class LimitUpResearchResult:
    start: str
    end: str
    trade_dates: list[str]
    detail_path: Path
    summary_path: Path
    theme_path: Path
    fundamentals_path: Path
    report_path: Path
    pool_path: Path | None
    detail: pd.DataFrame
    stock_summary: pd.DataFrame
    theme_summary: pd.DataFrame
    fundamentals: pd.DataFrame


THEMES: tuple[FineTheme, ...] = (
    FineTheme(
        name="AI液冷温控",
        description="AI服务器液冷、温控、散热和热管理链条。",
        concept_codes=("886044.TI",),
        industry_keywords=("温控", "热管理", "散热", "制冷"),
        name_keywords=("英维克", "高澜", "申菱", "佳力图", "依米康", "三花", "银轮"),
        seed_symbols=("002837.SZ", "300499.SZ", "002050.SZ", "301018.SZ", "603912.SH", "300249.SZ", "002126.SZ"),
        priority=10,
    ),
    FineTheme(
        name="AI_PCB载板",
        description="AI服务器PCB、高多层板、封装基板和高速互联板。",
        concept_codes=("885959.TI", "884092.TI"),
        industry_keywords=("印制电路板",),
        name_keywords=("沪电", "胜宏", "深南", "景旺", "世运", "崇达", "生益电子", "奥士康"),
        seed_symbols=("002463.SZ", "300476.SZ", "002916.SZ", "688183.SH", "603228.SH", "603920.SH", "002815.SZ", "002913.SZ"),
        priority=11,
    ),
    FineTheme(
        name="AI高速材料",
        description="覆铜板、铜箔、PEEK、半导体材料、膜材料和其他高速/高端材料。",
        concept_codes=("884091.TI", "886063.TI", "886020.TI", "881114.TI", "884057.TI", "884213.TI"),
        industry_keywords=("半导体材料", "金属新材料", "非金属材料", "磁性材料"),
        name_keywords=("生益", "华正", "南亚", "铜箔", "材料", "PEEK", "菲利华", "雅克", "联瑞", "沃特"),
        seed_symbols=("600183.SH", "603186.SH", "688519.SH", "300395.SZ", "603688.SH", "002409.SZ", "688300.SH"),
        priority=12,
    ),
    FineTheme(
        name="存储_HBM",
        description="存储芯片、存储模组、内存接口芯片和HBM相关链条。",
        concept_codes=("886042.TI",),
        industry_keywords=("存储", "半导体"),
        name_keywords=("存储", "澜起", "佰维", "江波龙", "兆易", "德明利", "深科技", "香农"),
        seed_symbols=("688525.SH", "301308.SZ", "688008.SH", "603986.SH", "001309.SZ", "000021.SZ", "300475.SZ"),
        priority=13,
    ),
    FineTheme(
        name="CPO光模块",
        description="CPO、光模块、光器件、光芯片和AI高速光互联。",
        concept_codes=("886033.TI",),
        industry_keywords=("光通信", "光学光电子"),
        name_keywords=("光模块", "光迅", "中际", "新易盛", "天孚", "源杰", "太辰光", "光库"),
        seed_symbols=("300308.SZ", "300502.SZ", "300394.SZ", "688498.SH", "002281.SZ", "000988.SZ", "300570.SZ", "300620.SZ"),
        priority=14,
    ),
    FineTheme(
        name="铜缆高速连接",
        description="AI服务器铜缆高速连接、连接器和高速线缆。",
        concept_codes=("886073.TI",),
        industry_keywords=("连接器",),
        name_keywords=("连接", "电缆", "线缆", "沃尔", "神宇", "兆龙"),
        seed_symbols=("002130.SZ", "300563.SZ", "300913.SZ", "300991.SZ", "002897.SZ"),
        priority=15,
    ),
    FineTheme(
        name="算力电力配套",
        description="智算中心上游电力、电气设备、线缆和能源配套。",
        industry_keywords=("电力", "火力发电", "水力发电", "电气设备", "线缆部件"),
        name_keywords=("豫能", "韶能", "顺钠", "华电", "远东", "汉缆", "电气", "电力", "能源"),
        seed_symbols=("001896.SZ", "000601.SZ", "000533.SZ", "600869.SH", "002498.SZ", "600396.SH", "600726.SH"),
        priority=16,
    ),
    FineTheme(
        name="AI芯片服务器算力",
        description="AI芯片、服务器、智算中心、算力租赁和国产算力基础设施。",
        concept_codes=("886102.TI", "886050.TI", "885957.TI", "886048.TI"),
        industry_keywords=("IT设备", "计算机设备"),
        name_keywords=("寒武纪", "海光", "曙光", "浪潮", "工业富联", "紫光", "神州数码", "拓维"),
        seed_symbols=("688256.SH", "688041.SH", "603019.SH", "000977.SZ", "601138.SH", "000938.SZ", "000034.SZ", "002261.SZ"),
        priority=18,
    ),
    FineTheme(
        name="AI应用大模型",
        description="大模型、AI办公、AI教育、语音视觉、端侧AI和行业应用。",
        concept_codes=("886108.TI", "886068.TI", "886070.TI"),
        industry_keywords=("软件服务", "互联网", "IT服务", "影视音像"),
        name_keywords=("大模型", "讯飞", "金山", "万兴", "云从", "拓尔思", "中文在线", "虹软"),
        seed_symbols=("002230.SZ", "688111.SH", "300624.SZ", "688327.SH", "300229.SZ", "300364.SZ", "688088.SH"),
        priority=19,
    ),
    FineTheme(
        name="机器人减速器丝杠",
        description="人形机器人丝杠、轴承、减速器、精密传动和关节传动。",
        concept_codes=("886008.TI",),
        industry_keywords=("机械基件", "机床制造", "专用机械"),
        name_keywords=("减速", "传动", "丝杠", "轴承", "谐波", "双环", "贝斯特", "五洲"),
        seed_symbols=("002472.SZ", "688017.SH", "002896.SZ", "603667.SH", "000837.SZ", "300580.SZ", "603009.SH", "603040.SH"),
        priority=20,
    ),
    FineTheme(
        name="机器人执行器伺服",
        description="人形机器人执行器、伺服、电机、运动控制和整机集成。",
        concept_codes=("886069.TI", "885517.TI"),
        industry_keywords=("机器人", "电机", "自动化设备", "工业机械"),
        name_keywords=("机器人", "执行器", "伺服", "电机", "汇川", "埃斯顿", "拓普", "三花"),
        seed_symbols=("002050.SZ", "601689.SH", "300124.SZ", "002747.SZ", "688160.SH", "603728.SH", "002979.SZ", "300503.SZ"),
        priority=21,
    ),
    FineTheme(
        name="机器人传感器视觉",
        description="机器人3D视觉、力传感器、触觉传感和环境感知。",
        concept_codes=("885946.TI",),
        industry_keywords=("传感器", "仪器仪表", "光学光电子"),
        name_keywords=("传感", "视觉", "奥比", "柯力", "汉威", "虹软"),
        seed_symbols=("688322.SH", "603662.SH", "300007.SZ", "688088.SH"),
        priority=22,
    ),
    FineTheme(
        name="半导体设备封装",
        description="半导体设备、先进封装、晶圆制造和关键工艺平台。",
        concept_codes=("884229.TI", "886009.TI", "881121.TI"),
        industry_keywords=("半导体设备", "半导体", "集成电路"),
        name_keywords=("北方华创", "中微", "华海清科", "拓荆", "长电", "通富", "中芯"),
        seed_symbols=("002371.SZ", "688012.SH", "688120.SH", "688072.SH", "600584.SH", "002156.SZ", "688981.SH"),
        priority=30,
    ),
    FineTheme(
        name="固态电池新能源",
        description="固态电池、电池材料、隔膜、电解质、结构件和新能源车链。",
        concept_codes=("886032.TI",),
        industry_keywords=("电池",),
        name_keywords=("固态", "电池", "锂", "电解", "隔膜", "恩捷", "科达利"),
        seed_symbols=("300750.SZ", "002594.SZ", "300014.SZ", "002812.SZ", "002850.SZ", "603659.SH"),
        priority=40,
    ),
    FineTheme(
        name="低空经济无人机",
        description="eVTOL、无人机、飞控导航、航空材料和低空基础设施。",
        concept_codes=("886067.TI",),
        industry_keywords=("航空", "运输设备"),
        name_keywords=("无人机", "低空", "万丰", "航天彩虹", "中无人机", "光电"),
        seed_symbols=("002085.SZ", "688297.SH", "002389.SZ", "002179.SZ", "600893.SH"),
        priority=50,
    ),
    FineTheme(
        name="商业航天卫星",
        description="商业航天、卫星互联网、遥感、导航和航天电子。",
        concept_codes=("886078.TI",),
        industry_keywords=("航空", "航天", "军工电子"),
        name_keywords=("卫星", "航天", "北斗", "海格", "中国卫星"),
        seed_symbols=("600118.SH", "600879.SH", "002025.SZ", "002465.SZ", "000768.SZ"),
        priority=51,
    ),
    FineTheme(
        name="创新药生物科技",
        description="创新药、ADC/双抗、自免肿瘤管线、出海BD和CXO/CDMO。",
        concept_codes=("886015.TI",),
        industry_keywords=("化学制药", "生物制药", "医疗保健", "医药商业"),
        name_keywords=("药", "生物", "医疗", "恒瑞", "百济", "荣昌", "科伦"),
        seed_symbols=("600276.SH", "688235.SH", "688506.SH", "688331.SH", "002422.SZ", "603259.SH"),
        priority=60,
    ),
    FineTheme(
        name="黄金有色稀土",
        description="黄金、稀土永磁、有色金属和资源品。",
        concept_codes=("885530.TI", "885343.TI"),
        industry_keywords=("黄金", "小金属", "铜", "铝", "铅锌", "稀土", "有色"),
        name_keywords=("黄金", "稀土", "北方稀土", "洛阳钼业", "紫金", "招金"),
        seed_symbols=("000506.SZ", "600489.SH", "601899.SH", "600111.SH", "603993.SH"),
        priority=70,
    ),
    FineTheme(
        name="电力核电聚变",
        description="核电、可控核聚变、电力设备、电网和新型电力系统。",
        concept_codes=("886065.TI", "885571.TI"),
        industry_keywords=("电力", "火力发电", "水力发电", "核电"),
        name_keywords=("核", "电力", "电气", "东方电气", "中国核电", "海陆重工"),
        seed_symbols=("601985.SH", "600875.SH", "002255.SZ", "601727.SH"),
        priority=80,
    ),
    FineTheme(
        name="军工电子装备",
        description="军工电子、地面兵装、航空航天装备和国防信息化。",
        concept_codes=("884266.TI", "884180.TI"),
        industry_keywords=("军工电子", "地面兵装", "航空装备", "航天装备"),
        name_keywords=("军工", "航天", "兵装", "中航", "国睿", "振华"),
        seed_symbols=("000547.SZ", "000576.SZ", "000733.SZ", "600760.SH", "600562.SH"),
        priority=90,
    ),
    FineTheme(
        name="化工材料工业气体",
        description="基础化工、化学制品、工业气体、染料、塑料橡胶和通用材料。",
        industry_keywords=("化学制品", "化工原料", "农药化肥", "染料涂料", "化纤", "塑料", "橡胶", "工业气体", "矿物制品"),
        name_keywords=("化工", "材料", "气体", "染料", "塑料", "橡胶", "化学", "玻纤"),
        priority=120,
    ),
    FineTheme(
        name="地产基建建材",
        description="房地产、建筑工程、建筑装饰、建材和园区开发。",
        industry_keywords=("全国地产", "区域地产", "房产服务", "工程建设", "建筑工程", "建筑装饰", "水泥", "玻璃", "其他建材", "园区开发"),
        name_keywords=("地产", "建设", "建材", "水泥", "装饰", "园区", "城建"),
        priority=121,
    ),
    FineTheme(
        name="机械设备制造",
        description="通用机械、专用机械、工程机械、机床制造和设备制造。",
        industry_keywords=("专用机械", "通用机械", "工程机械", "机床制造", "机械基件", "纺织机械", "农用机械"),
        name_keywords=("机械", "机床", "装备", "重工", "精工", "智能装备"),
        priority=122,
    ),
    FineTheme(
        name="汽车零部件整车",
        description="汽车零部件、汽车整车、汽车电子和汽配服务。",
        industry_keywords=("汽车配件", "汽车整车", "汽车服务", "摩托车"),
        name_keywords=("汽车", "汽配", "车", "轮胎", "电驱"),
        priority=123,
    ),
    FineTheme(
        name="消费纺织食品",
        description="食品饮料、纺织服饰、家居、造纸包装、商贸零售和旅游消费。",
        industry_keywords=("食品", "白酒", "软饮料", "纺织", "服饰", "家居用品", "造纸", "包装", "百货", "超市连锁", "旅游", "酒店餐饮"),
        name_keywords=("食品", "酒", "纺织", "服饰", "家居", "纸业", "包装", "旅游", "酒店"),
        priority=124,
    ),
    FineTheme(
        name="传媒游戏教育",
        description="传媒、广告营销、游戏、影视、出版和教育。",
        industry_keywords=("广告包装", "影视音像", "出版业", "文教休闲", "互联网", "软件服务"),
        name_keywords=("传媒", "文化", "影视", "游戏", "教育", "出版", "在线"),
        priority=125,
    ),
    FineTheme(
        name="农业养殖",
        description="种植、养殖、饲料、农林牧渔和农产品加工。",
        industry_keywords=("农业综合", "种植业", "林业", "渔业", "饲料", "农产品加工", "红黄酒"),
        name_keywords=("农业", "养殖", "种业", "饲料", "食品"),
        priority=126,
    ),
    FineTheme(
        name="环保公用事业",
        description="环保、水务、燃气、公共交通和公用事业。",
        industry_keywords=("环境保护", "水务", "供气供热", "公共交通", "电力"),
        name_keywords=("环保", "水务", "燃气", "节能", "公用"),
        priority=127,
    ),
    FineTheme(
        name="金融证券保险",
        description="银行、证券、保险、多元金融和金融科技。",
        industry_keywords=("银行", "证券", "保险", "多元金融"),
        name_keywords=("银行", "证券", "保险", "金融", "信托"),
        priority=128,
    ),
    FineTheme(
        name="交通物流港口",
        description="物流、航运、港口、高速公路、铁路和机场。",
        industry_keywords=("物流", "仓储物流", "港口", "水运", "航空", "铁路", "高速公路", "公路"),
        name_keywords=("物流", "港", "航运", "铁路", "机场", "高速"),
        priority=129,
    ),
)


def _stats_dir(config: dict) -> Path:
    return Path(config["output"].get("statistics_dir", "output/statistics"))


def _research_dir() -> Path:
    return Path("docs/research")


def _yyyymmdd(value: str | date | pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def default_recent_window(months: int = 6, today: date | None = None) -> tuple[str, str]:
    current = pd.Timestamp(today or date.today())
    start = current - pd.DateOffset(months=months)
    return start.strftime("%Y%m%d"), current.strftime("%Y%m%d")


def _client(config: dict) -> TushareClient:
    tushare_cfg = config.get("tushare", {}) or {}
    primary = tushare_cfg.get("token")
    if not primary:
        configured = tushare_cfg.get("tokens", []) or []
        primary = configured[0] if configured else None
    if not primary:
        return TushareClient.from_config(config)
    scoped = dict(config)
    scoped["tushare"] = {"token": primary, "tokens": []}
    return TushareClient.from_config(scoped)


def _call(client: TushareClient, symbol: str, api_name: str, callback: Callable[[object], object]):
    return client.call(symbol, api_name, callback)


def fetch_trade_dates(
    config: dict,
    start: str,
    end: str,
    pro: Any | None = None,
    client: TushareClient | None = None,
) -> list[str]:
    start = _yyyymmdd(start)
    end = _yyyymmdd(end)
    try:
        if pro is not None:
            cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1", fields="cal_date,is_open")
        else:
            active_client = client or _client(config)
            cal = _call(
                active_client,
                "trade_cal",
                "trade_cal",
                lambda api: api.trade_cal(
                    exchange="SSE",
                    start_date=start,
                    end_date=end,
                    is_open="1",
                    fields="cal_date,is_open",
                ),
            )
        if cal is not None and not cal.empty and "cal_date" in cal.columns:
            return sorted(cal["cal_date"].dropna().astype(str).unique().tolist())
    except Exception:
        pass
    return [d.strftime("%Y%m%d") for d in pd.bdate_range(start=start, end=end)]


def fetch_limit_up_detail(
    config: dict,
    trade_dates: Iterable[str],
    pro: Any | None = None,
    client: TushareClient | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    active_client = client if pro is None else None
    fields = LIMIT_FIELDS
    for trade_date in trade_dates:
        day = str(trade_date).replace("-", "")
        try:
            if pro is not None:
                raw = pro.limit_list_d(trade_date=day, fields=fields)
            else:
                active_client = active_client or _client(config)
                raw = _call(
                    active_client,
                    day,
                    "limit_list_d",
                    lambda api, d=day: api.limit_list_d(trade_date=d, fields=fields),
                )
        except Exception:
            raw = pd.DataFrame()
        detail = clean_limit_detail(raw)
        if detail.empty or "limit_type" not in detail.columns:
            continue
        up = detail[detail["limit_type"].astype(str).str.upper() == "U"].copy()
        if not up.empty:
            frames.append(up)
    if not frames:
        return pd.DataFrame(columns=LIMIT_FIELDS.split(",") + ["limit_type"])
    result = pd.concat(frames, ignore_index=True)
    result["trade_date"] = result["trade_date"].astype(str)
    result["ts_code"] = result["ts_code"].astype(str)
    result["name"] = result.get("name", "").astype(str)
    return result.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)


def fetch_theme_members(
    config: dict,
    pro: Any | None = None,
    client: TushareClient | None = None,
) -> dict[str, set[str]]:
    members: dict[str, set[str]] = {theme.name: set(theme.seed_symbols) for theme in THEMES}
    active_client = client if pro is None else None
    for theme in THEMES:
        for concept_code in theme.concept_codes:
            try:
                if pro is not None:
                    df = pro.ths_member(ts_code=concept_code)
                else:
                    active_client = active_client or _client(config)
                    df = _call(
                        active_client,
                        concept_code,
                        "ths_member",
                        lambda api, code=concept_code: api.ths_member(ts_code=code),
                    )
            except Exception:
                df = pd.DataFrame()
            if df is None or df.empty:
                continue
            code_col = "con_code" if "con_code" in df.columns else "ts_code"
            if code_col not in df.columns:
                continue
            members[theme.name].update(df[code_col].dropna().astype(str).str.upper().tolist())
    return members


def _theme_score(theme: FineTheme, row: pd.Series, member_symbols: set[str]) -> int:
    symbol = str(row.get("ts_code", "")).upper()
    name = str(row.get("name", ""))
    industry = str(row.get("industry", ""))
    score = 0
    if symbol in member_symbols:
        score += 100
    if any(keyword and keyword in industry for keyword in theme.industry_keywords):
        score += 12
    if any(keyword and keyword in name for keyword in theme.name_keywords):
        score += 18
    return score


def classify_limit_up_stocks(detail: pd.DataFrame, theme_members: dict[str, set[str]]) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()

    rows = []
    for symbol, group in detail.groupby("ts_code", sort=False):
        latest = group.sort_values("trade_date").iloc[-1]
        scores = []
        for theme in THEMES:
            score = _theme_score(theme, latest, theme_members.get(theme.name, set()))
            if score > 0:
                scores.append((theme.priority, -score, theme.name, score))
        scores.sort()
        tags = [name for _, _, name, _ in scores]
        primary = tags[0] if tags else "其他涨停未细分"
        limit_times = pd.to_numeric(group.get("limit_times"), errors="coerce")
        open_times = pd.to_numeric(group.get("open_times"), errors="coerce")
        turnover = pd.to_numeric(group.get("turnover_ratio"), errors="coerce")
        amount = pd.to_numeric(group.get("amount"), errors="coerce")
        first_times = group.get("first_time", pd.Series(dtype=object)).dropna().astype(str)
        rows.append(
            {
                "ts_code": symbol,
                "name": latest.get("name", ""),
                "industry": latest.get("industry", ""),
                "primary_theme": primary,
                "theme_tags": ",".join(tags) if tags else "其他涨停未细分",
                "limit_up_count": int(len(group)),
                "first_limit_date": str(group["trade_date"].min()),
                "last_limit_date": str(group["trade_date"].max()),
                "max_limit_times": int(limit_times.max()) if limit_times.notna().any() else None,
                "avg_open_times": round(float(open_times.mean()), 2) if open_times.notna().any() else None,
                "avg_turnover_ratio": round(float(turnover.mean()), 2) if turnover.notna().any() else None,
                "avg_amount": round(float(amount.mean()), 2) if amount.notna().any() else None,
                "latest_close": latest.get("close"),
                "latest_pct_chg": latest.get("pct_chg"),
                "latest_pe": latest.get("pe"),
                "latest_float_mv": latest.get("float_mv"),
                "latest_total_mv": latest.get("total_mv"),
                "first_board_time_sample": first_times.iloc[0] if not first_times.empty else "",
            }
        )
    summary = pd.DataFrame(rows)
    numeric_cols = [
        "limit_up_count",
        "max_limit_times",
        "avg_open_times",
        "avg_turnover_ratio",
        "avg_amount",
        "latest_close",
        "latest_pct_chg",
        "latest_pe",
        "latest_float_mv",
        "latest_total_mv",
    ]
    for col in numeric_cols:
        if col in summary.columns:
            summary[col] = pd.to_numeric(summary[col], errors="coerce")
    return summary.sort_values(["limit_up_count", "last_limit_date", "latest_total_mv"], ascending=[False, False, False]).reset_index(drop=True)


def build_theme_summary(stock_summary: pd.DataFrame) -> pd.DataFrame:
    if stock_summary.empty:
        return pd.DataFrame(
            columns=["theme", "stock_count", "limit_up_events", "avg_limit_up_count", "leaders", "avg_pe", "avg_total_mv"]
        )
    rows = []
    for theme, group in stock_summary.groupby("primary_theme", dropna=False):
        leaders = group.sort_values(["limit_up_count", "last_limit_date"], ascending=False).head(8)
        rows.append(
            {
                "theme": theme,
                "stock_count": int(len(group)),
                "limit_up_events": int(group["limit_up_count"].sum()),
                "avg_limit_up_count": round(float(group["limit_up_count"].mean()), 2),
                "leaders": ", ".join(f"{row['name']}({row['ts_code']})" for _, row in leaders.iterrows()),
                "avg_pe": round(float(pd.to_numeric(group.get("latest_pe"), errors="coerce").mean()), 2),
                "avg_total_mv": round(float(pd.to_numeric(group.get("latest_total_mv"), errors="coerce").mean()), 2),
            }
        )
    return pd.DataFrame(rows).sort_values(["limit_up_events", "stock_count"], ascending=False).reset_index(drop=True)


def _fetch_latest_fundamentals(
    config: dict,
    symbols: list[str],
    start: str,
    end: str,
    pro: Any | None = None,
    client: TushareClient | None = None,
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    active_client = client if pro is None else None
    lookback_start = (pd.Timestamp(start) - pd.DateOffset(months=18)).strftime("%Y%m%d")
    rows = []
    fields = ",".join(
        [
            "ts_code",
            "ann_date",
            "end_date",
            "eps",
            "bps",
            "grossprofit_margin",
            "netprofit_margin",
            "roe",
            "roe_waa",
            "debt_to_assets",
            "or_yoy",
            "netprofit_yoy",
            "dt_netprofit_yoy",
            "ocf_yoy",
            "q_sales_yoy",
            "q_roe",
            "q_ocf_to_sales",
        ]
    )
    for symbol in symbols:
        try:
            if pro is not None:
                df = pro.fina_indicator(ts_code=symbol, start_date=lookback_start, end_date=end, fields=fields)
            else:
                active_client = active_client or _client(config)
                df = _call(
                    active_client,
                    symbol,
                    "fina_indicator",
                    lambda api, s=symbol: api.fina_indicator(
                        ts_code=s,
                        start_date=lookback_start,
                        end_date=end,
                        fields=fields,
                    ),
                )
        except Exception:
            df = pd.DataFrame()
        if df is None or df.empty:
            continue
        latest = df.sort_values(["end_date", "ann_date"], ascending=False).iloc[0].to_dict()
        rows.append(latest)
    result = pd.DataFrame(rows)
    for col in result.columns:
        if col not in {"ts_code", "ann_date", "end_date"}:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    return result


def _fmt_num(value: Any, digits: int = 2, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if pd.isna(number):
        return "-"
    return f"{number:.{digits}f}{suffix}"


def _fmt_money_wan(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if pd.isna(number):
        return "-"
    return f"{number / 100000000:.1f}亿"


def _fundamental_note(row: pd.Series) -> str:
    notes: list[str] = []
    pe = pd.to_numeric(row.get("latest_pe"), errors="coerce")
    roe = pd.to_numeric(row.get("roe"), errors="coerce")
    revenue_yoy = pd.to_numeric(row.get("or_yoy"), errors="coerce")
    profit_yoy = pd.to_numeric(row.get("netprofit_yoy"), errors="coerce")
    debt = pd.to_numeric(row.get("debt_to_assets"), errors="coerce")
    limit_count = int(row.get("limit_up_count", 0) or 0)

    if limit_count >= 5:
        notes.append("半年涨停频率高，属于短线资金反复确认的活跃标的")
    elif limit_count >= 2:
        notes.append("半年内多次涨停，具备阶段性主题弹性")
    else:
        notes.append("单次涨停驱动更强，需核对事件持续性")

    if pd.notna(pe):
        if pe <= 0:
            notes.append("PE为空或为负，盈利稳定性需要优先复核")
        elif pe > 100:
            notes.append("PE偏高，股价对业绩兑现要求较高")
        elif pe < 40:
            notes.append("PE相对可观察，估值压力低于高弹性主题股")

    if pd.notna(roe) and roe >= 10:
        notes.append("ROE达到两位数，盈利质量有一定支撑")
    if pd.notna(revenue_yoy) and revenue_yoy >= 20:
        notes.append("收入同比增长较快")
    if pd.notna(profit_yoy) and profit_yoy >= 20:
        notes.append("净利润同比增长较快")
    if pd.notna(debt) and debt >= 70:
        notes.append("资产负债率偏高，需关注现金流和融资压力")
    return "；".join(notes) + "。"


def _write_report(
    result: LimitUpResearchResult,
    min_limit_count: int,
    pool_prefix: str,
) -> Path:
    report_path = result.report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    stock_summary = result.stock_summary
    theme_summary = result.theme_summary
    fundamentals = result.fundamentals
    merged = stock_summary.merge(fundamentals, on="ts_code", how="left") if not fundamentals.empty else stock_summary.copy()

    lines = [
        f"# 最近半年涨停股票池与基本面分析（{result.start} ~ {result.end}）",
        "",
        f"生成日期：{date.today().strftime('%Y-%m-%d')}",
        "",
        "结论属性：本报告由本地程序抓取 Tushare 涨停明细，并由大模型按细分产业链做研究归纳；用于股票池观察、回测和人工复盘，不构成投资建议。",
        "",
        "## 1. 数据口径",
        "",
        f"- 交易日范围：{result.start} ~ {result.end}，有效交易日 {len(result.trade_dates)} 个。",
        f"- 涨停事件：{len(result.detail)} 条；唯一涨停股票：{len(stock_summary)} 只。",
        f"- 入池阈值：每只股票半年涨停次数 >= {min_limit_count}。",
        f"- 涨停来源：Tushare `limit_list_d`；细分分类来源：同花顺概念成员、公司名称/行业关键词和内置精选种子。",
        f"- 基本面来源：Tushare `fina_indicator` 最近一期财务指标，以及涨停明细中的 PE、市值、换手率等字段。",
        f"- 股票池文件：`{result.pool_path}`。",
        "",
        "## 2. 细分主题热度",
        "",
        "| 细分主题 | 股票数 | 涨停次数 | 平均涨停次数 | 代表股票 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for _, row in theme_summary.head(30).iterrows():
        lines.append(
            f"| {row['theme']} | {int(row['stock_count'])} | {int(row['limit_up_events'])} | "
            f"{_fmt_num(row['avg_limit_up_count'])} | {row['leaders']} |"
        )

    lines.extend(
        [
            "",
            "## 3. 高频涨停股票",
            "",
            "| 代码 | 名称 | 细分主题 | 半年涨停 | 最近涨停 | PE | 总市值 | 观察要点 |",
            "| --- | --- | --- | ---: | --- | ---: | ---: | --- |",
        ]
    )
    for _, row in merged.head(60).iterrows():
        lines.append(
            f"| {row['ts_code']} | {row['name']} | {row['primary_theme']} | {int(row['limit_up_count'])} | "
            f"{row['last_limit_date']} | {_fmt_num(row.get('latest_pe'))} | {_fmt_money_wan(row.get('latest_total_mv'))} | "
            f"{_fundamental_note(row)} |"
        )

    lines.extend(
        [
            "",
            "## 4. 大模型分主题基本面复盘",
            "",
            "本轮细分的重点是把原先较粗的 AI/科技大类拆开：液冷温控、PCB载板、高速材料、存储HBM、CPO光模块、铜缆高速连接、AI芯片服务器算力和AI应用分别入池。涨停频率只能说明资金关注度，基本面仍要看收入增速、利润增速、ROE、现金流和资产负债率是否支撑估值。",
            "",
        ]
    )
    for _, theme_row in theme_summary.head(12).iterrows():
        theme = str(theme_row["theme"])
        subset = merged[merged["primary_theme"] == theme].head(8)
        if subset.empty:
            continue
        lines.extend(
            [
                f"### {theme}",
                "",
                f"{theme} 半年内覆盖 {int(theme_row['stock_count'])} 只涨停股，合计 {int(theme_row['limit_up_events'])} 次涨停。"
                "优先观察涨停频率高、最近涨停时间近、且财务增速/ROE不弱的公司；对 PE 过高或盈利为空的公司，只适合作为事件观察池。",
                "",
                "| 代码 | 名称 | 涨停 | 最近涨停 | ROE | 收入增速 | 净利增速 | 毛利率 | 资产负债率 | 简评 |",
                "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for _, row in subset.iterrows():
            lines.append(
                f"| {row['ts_code']} | {row['name']} | {int(row['limit_up_count'])} | {row['last_limit_date']} | "
                f"{_fmt_num(row.get('roe'), 1, '%')} | {_fmt_num(row.get('or_yoy'), 1, '%')} | "
                f"{_fmt_num(row.get('netprofit_yoy'), 1, '%')} | {_fmt_num(row.get('grossprofit_margin'), 1, '%')} | "
                f"{_fmt_num(row.get('debt_to_assets'), 1, '%')} | {_fundamental_note(row)} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 5. 产物清单",
            "",
            f"- 涨停明细：`{result.detail_path}`",
            f"- 个股汇总：`{result.summary_path}`",
            f"- 主题汇总：`{result.theme_path}`",
            f"- 基本面快照：`{result.fundamentals_path}`",
            f"- 股票池：`{result.pool_path}`",
            "",
            "## 6. 风险提示",
            "",
            "- 本报告使用当前上市公司和当前概念成分，存在幸存者偏差和概念成分漂移。",
            "- 涨停数据代表资金行为，不等同于基本面兑现；高 PE、负 PE 或财务指标缺失公司需要逐一核对公告和财报。",
            "- 细分分类是研究辅助标签，可能因公司业务变化、概念成分宽泛或名称关键词误判而需要人工修正。",
            "- 该研究链路不改变 Backtrader 回测的成交价格、手续费、滑点、涨跌停、T+1、成交量限制或 CSV 字段。",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _save_theme_pools(
    config: dict,
    stock_summary: pd.DataFrame,
    start: str,
    end: str,
    min_limit_count: int,
    pool_prefix: str,
) -> Path | None:
    if stock_summary.empty:
        return None
    eligible = stock_summary[stock_summary["limit_up_count"] >= int(min_limit_count)].copy()
    if eligible.empty:
        return None

    suffix = f"{start}_{end}"
    last_path = save_stock_pool(
        config,
        f"{pool_prefix}_全部_{suffix}",
        eligible[["ts_code", "name"]].to_dict("records"),
        description=f"{start}~{end} 半年涨停股票，阈值 {min_limit_count} 次。",
        merge=False,
    )
    high_freq = eligible[eligible["limit_up_count"] >= max(3, int(min_limit_count))]
    if not high_freq.empty:
        last_path = save_stock_pool(
            config,
            f"{pool_prefix}_高频_{suffix}",
            high_freq[["ts_code", "name"]].to_dict("records"),
            description=f"{start}~{end} 半年高频涨停股票，涨停次数 >= {max(3, int(min_limit_count))}。",
            merge=False,
        )
    for theme, group in eligible.groupby("primary_theme", sort=False):
        safe_theme = str(theme).replace("/", "_").replace(",", "_").replace(" ", "")
        last_path = save_stock_pool(
            config,
            f"{pool_prefix}_{safe_theme}_{suffix}",
            group[["ts_code", "name"]].to_dict("records"),
            description=f"{start}~{end} 半年涨停细分主题: {theme}，阈值 {min_limit_count} 次。",
            merge=False,
        )
    return last_path


def save_limit_up_research(
    config: dict,
    start: str | None = None,
    end: str | None = None,
    months: int = 6,
    min_limit_count: int = 1,
    save_pools: bool = True,
    pool_prefix: str = "半年涨停",
    fundamental_top: int = 80,
    pro: Any | None = None,
) -> LimitUpResearchResult:
    if not start or not end:
        default_start, default_end = default_recent_window(months=months)
        start = start or default_start
        end = end or default_end
    start = _yyyymmdd(start)
    end = _yyyymmdd(end)
    stats_dir = _stats_dir(config)
    stats_dir.mkdir(parents=True, exist_ok=True)
    research_dir = _research_dir()
    research_dir.mkdir(parents=True, exist_ok=True)

    client = None if pro is not None else _client(config)
    trade_dates = fetch_trade_dates(config, start, end, pro=pro, client=client)
    if trade_dates:
        start = trade_dates[0]
        end = trade_dates[-1]

    detail = fetch_limit_up_detail(config, trade_dates, pro=pro, client=client)
    theme_members = fetch_theme_members(config, pro=pro, client=client)
    stock_summary = classify_limit_up_stocks(detail, theme_members)
    theme_summary = build_theme_summary(stock_summary)
    top_symbols = stock_summary.head(max(0, int(fundamental_top)))["ts_code"].astype(str).tolist()
    fundamentals = _fetch_latest_fundamentals(config, top_symbols, start, end, pro=pro, client=client)

    stem = f"limit_up_research_{start}_{end}"
    detail_path = stats_dir / f"{stem}_detail.csv"
    summary_path = stats_dir / f"{stem}_stocks.csv"
    theme_path = stats_dir / f"{stem}_themes.csv"
    fundamentals_path = stats_dir / f"{stem}_fundamentals.csv"
    report_path = research_dir / f"{stem}.md"

    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    stock_summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    theme_summary.to_csv(theme_path, index=False, encoding="utf-8-sig")
    fundamentals.to_csv(fundamentals_path, index=False, encoding="utf-8-sig")
    pool_path = _save_theme_pools(config, stock_summary, start, end, min_limit_count, pool_prefix) if save_pools else None

    result = LimitUpResearchResult(
        start=start,
        end=end,
        trade_dates=trade_dates,
        detail_path=detail_path,
        summary_path=summary_path,
        theme_path=theme_path,
        fundamentals_path=fundamentals_path,
        report_path=report_path,
        pool_path=pool_path,
        detail=detail,
        stock_summary=stock_summary,
        theme_summary=theme_summary,
        fundamentals=fundamentals,
    )
    _write_report(result, min_limit_count=min_limit_count, pool_prefix=pool_prefix)
    return result
