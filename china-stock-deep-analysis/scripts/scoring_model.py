#!/usr/bin/env python3
"""Industry-adaptive scoring model and dashboard JSON builder.

Backward compatible:
  scoring_model.py --input raw.json --out dashboard.json

New optional args:
  --industry <行业>
  --catalyst-score <0-10>
"""
import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCORE_VERSION = "china-stock-score-v3.0-industry-adaptive"

BASE_WEIGHTS = {
    "行业景气度": 0.15,
    "公司竞争力": 0.20,
    "财务质量": 0.20,
    "成长确定性": 0.15,
    "估值性价比": 0.15,
    "催化剂强度": 0.10,
    "风险可控性": 0.05,
}

INDUSTRY_WEIGHTS = {
    "券商": {"行业景气度": 0.18, "公司竞争力": 0.18, "财务质量": 0.18, "成长确定性": 0.12, "估值性价比": 0.22, "催化剂强度": 0.08, "风险可控性": 0.04},
    "银行": {"行业景气度": 0.10, "公司竞争力": 0.18, "财务质量": 0.24, "成长确定性": 0.08, "估值性价比": 0.22, "催化剂强度": 0.05, "风险可控性": 0.13},
    "科技": {"行业景气度": 0.18, "公司竞争力": 0.20, "财务质量": 0.15, "成长确定性": 0.22, "估值性价比": 0.10, "催化剂强度": 0.10, "风险可控性": 0.05},
    "制造业": {"行业景气度": 0.13, "公司竞争力": 0.20, "财务质量": 0.22, "成长确定性": 0.15, "估值性价比": 0.15, "催化剂强度": 0.08, "风险可控性": 0.07},
}


def to_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None or x == "" or str(x).lower() in {"none", "nan", "null", "-"}:
            return default
        v = float(str(x).replace(",", "").replace("%", ""))
        return default if math.isnan(v) or math.isinf(v) else v
    except Exception:
        return default


def yi(x: Any) -> Optional[float]:
    v = to_float(x)
    return None if v is None else round(v / 1e8, 2)


def pct(x: Any) -> Optional[float]:
    v = to_float(x)
    return None if v is None else round(v, 2)


def clamp(x: float, a: float = 0, b: float = 10) -> float:
    return max(a, min(b, x))


def latest_annual(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return next((x for x in rows if "年报" in str(x.get("REPORT_DATE_NAME", ""))), rows[0] if rows else {})


def first_non_none(*vals: Any) -> Any:
    for v in vals:
        if v is not None and v != "":
            return v
    return None


def fmt(v: Any, suffix: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        s = f"{v:.2f}".rstrip("0").rstrip(".")
    else:
        s = str(v)
    return s + suffix


def industry_detect(name: str = "", industry_field: str = "") -> str:
    text = f"{name} {industry_field}".lower()
    rules = [
        ("券商", ["证券", "券商", "broker", "capital", "中信建投", "华泰", "国泰君安", "东方财富"]),
        ("银行", ["银行", "bank"]),
        ("科技", ["科技", "软件", "半导体", "芯片", "ai", "人工智能", "云", "互联网", "平台", "数据", "tesla", "nio", "bilibili", "alibaba", "jd.com", "pdd", "baidu", "腾讯", "阿里", "百度", "京东", "拼多多", "美团", "字节", "网易", "快手", "小米", "华为", "利欧", "蓝色光标", "分众", "数字营销"]),
        ("制造业", ["制造", "机械", "设备", "汽车", "新能源", "电池", "光伏", "电子", "材料", "工业", "automation"]),
        ("消费", ["食品", "饮料", "消费", "零售", "免税", "酒", "餐饮"]),
        ("医药", ["医药", "生物", "医疗", "药", "health", "pharma"]),
        ("周期资源", ["煤", "钢", "有色", "铜", "铝", "石油", "化工", "资源", "矿"]),
    ]
    for label, keys in rules:
        if any(k.lower() in text for k in keys):
            return label
    return industry_field if industry_field else "综合"


def industry_norm(ind: str) -> str:
    if not ind or ind.lower() in ('none', 'null', ''):
        return "综合"
    if "券" in ind or "证券" in ind:
        return "券商"
    if "银行" in ind:
        return "银行"
    if any(k in ind.lower() for k in ["科技", "软件", "芯片", "半导体", "互联网", "ai", "数字营销", "平台"]):
        return "科技"
    if any(k in ind for k in ["制造", "设备", "汽车", "电子", "材料", "工业", "新能源"]):
        return "制造业"
    return ind or "综合"


def weights_for(industry: str) -> Dict[str, float]:
    return INDUSTRY_WEIGHTS.get(industry_norm(industry), BASE_WEIGHTS)


def quote(raw: Dict[str, Any]) -> Dict[str, Any]:
    qs = raw.get("quote_sina") or {}
    qt = raw.get("quote_tencent") or {}
    qy = raw.get("quote_yahoo") or {}
    # Prefer Tencent for CN/HK valuation fields, Yahoo for US; fill gaps from all sources.
    market_key = raw.get("market_key")
    primary = qy if market_key == "us" and qy else (qt if qt else (qs if qs else qy))
    q = dict(primary)
    for src in [qt, qs, qy]:
        for k, v in src.items():
            q.setdefault(k, v)
    q["price"] = first_non_none(q.get("price"), qt.get("price"), qs.get("price"), qy.get("price"))
    q["pct"] = first_non_none(q.get("pct"), qt.get("pct"), qs.get("pct"), qy.get("pct"))
    return q


def score_by_market_cap(mkt: Optional[float]) -> float:
    # Competitiveness proxy based on market-cap percentile-like buckets.
    if mkt is None:
        return 5.6
    if mkt >= 5000:
        return 9.0
    if mkt >= 2000:
        return 8.2
    if mkt >= 800:
        return 7.2
    if mkt >= 300:
        return 6.3
    if mkt >= 100:
        return 5.4
    return 4.5


def calc_scores(metrics: Dict[str, Any], industry: str, catalyst_score: Optional[float]) -> Tuple[List[Dict[str, Any]], float, List[str], Dict[str, float]]:
    roe = to_float(metrics.get("roe"), 0) or 0
    np_growth = to_float(metrics.get("np_growth"), 0) or 0
    latest_np_growth = to_float(metrics.get("latest_np_growth"), 0) or 0
    rev_growth = to_float(metrics.get("rev_growth"), 0) or 0
    pb = to_float(metrics.get("pb"))
    pe = to_float(metrics.get("pe"))
    mkt = to_float(metrics.get("mktcap_yi"))
    cashflow = to_float(metrics.get("cashflow"))
    gross_margin = to_float(metrics.get("gross_margin"))
    rd_ratio = to_float(metrics.get("rd_ratio"))
    dividend_yield = to_float(metrics.get("dividend_yield"))
    npl_ratio = to_float(metrics.get("npl_ratio"))
    nim = to_float(metrics.get("nim"))
    turnover = to_float(metrics.get("turnover"))
    amount_yi = to_float(metrics.get("amount_yi"))

    notes: List[str] = []
    ind = industry_norm(industry)

    industry_score = 5.8
    if ind == "券商":
        industry_score += 0.8 if amount_yi and amount_yi > 5 else 0
        industry_score += 0.5 if latest_np_growth > 20 else -0.4 if latest_np_growth < 0 else 0
    elif ind == "银行":
        industry_score += 0.5 if dividend_yield and dividend_yield > 4 else 0
        industry_score += 0.5 if npl_ratio and npl_ratio < 1.5 else -0.5 if npl_ratio and npl_ratio > 2 else 0
        industry_score += 0.4 if nim and nim > 1.8 else 0
    elif ind == "科技":
        industry_score += 0.8 if rev_growth > 20 else -0.5 if rev_growth < 0 else 0
        industry_score += 0.4 if rd_ratio and rd_ratio > 8 else 0
    elif ind == "制造业":
        industry_score += 0.6 if gross_margin and gross_margin > 25 else -0.4 if gross_margin and gross_margin < 12 else 0
        industry_score += 0.4 if turnover and turnover > 1 else 0
    else:
        industry_score += 0.4 if rev_growth > 10 else -0.3 if rev_growth < 0 else 0

    comp_score = score_by_market_cap(mkt)

    # Financial quality: stronger differentiation via ROE ceilings.
    financial_score = 4.5 + roe / 3
    if cashflow is not None and cashflow > 0:
        financial_score += 0.8
    if np_growth > 0:
        financial_score += 0.4
    if roe > 15:
        financial_score = min(financial_score + 0.8, 8.5)
        notes.append("ROE>15%，财务质量上限提升到8.5区间。")
    elif roe < 5:
        financial_score = min(financial_score, 4.0)
        notes.append("ROE<5%，财务质量上限压到4分附近。")
    if latest_np_growth < 0:
        financial_score -= 0.8

    growth_score = 4.8
    if np_growth > 30:
        growth_score = 8.2
        notes.append("净利增速>30%，成长确定性可进入8分以上。")
    elif np_growth > 15:
        growth_score = 7.0
    elif np_growth > 0:
        growth_score = 6.0
    else:
        growth_score = 4.2
    if rev_growth > 20:
        growth_score += 0.8 if ind == "科技" else 0.5
    elif rev_growth < 0:
        growth_score -= 0.8
    if latest_np_growth < 0:
        growth_score -= 1.0

    valuation_score = 5.0
    if pb is not None:
        valuation_score += 1.5 if pb < 0.7 else 0.9 if pb < 1 else -0.8 if pb > 3 else 0
    if pe is not None:
        valuation_score += 1.2 if pe > 0 and pe < 12 else 0.5 if pe > 0 and pe < 20 else -1.2 if pe > 50 else -0.5 if pe <= 0 else 0
    if pb is not None and pb < 0.7 and roe > 10:
        valuation_score = max(valuation_score, 8.2)
        notes.append("PB<0.7且ROE稳定>10%，估值性价比进入8分以上。")
    if ind in {"券商", "银行"} and pb is not None and pb < 1 and roe > 8:
        valuation_score += 0.5

    catalyst = catalyst_score if catalyst_score is not None else 5.8
    if catalyst_score is None:
        if ind == "券商" and amount_yi and amount_yi > 5:
            catalyst += 0.8
        if latest_np_growth > 20:
            catalyst += 0.7
        if rev_growth > 20 and ind == "科技":
            catalyst += 0.6

    risk_score = 6.8
    if latest_np_growth < 0:
        risk_score -= 2.0
        notes.append("单季度/最新期利润下滑或亏损，风险可控性直接扣2分。")
    if pe is not None and pe > 80:
        risk_score -= 1.0
    if pb is not None and pb < 1:
        risk_score += 0.4
    if cashflow is not None and cashflow < 0:
        risk_score -= 1.0

    # Industry-specific metric refinements.
    if ind == "银行":
        if dividend_yield and dividend_yield > 5:
            financial_score += 0.4; valuation_score += 0.5
        if npl_ratio and npl_ratio > 2:
            risk_score -= 1.0; financial_score -= 0.5
        if nim and nim < 1.5:
            financial_score -= 0.5
    elif ind == "科技":
        if rd_ratio and rd_ratio > 10:
            comp_score += 0.5
        if rev_growth > 25:
            growth_score += 0.5
    elif ind == "制造业":
        if gross_margin and gross_margin > 30:
            financial_score += 0.5
        if turnover and turnover < 0.8:
            risk_score -= 0.4
    elif ind == "券商":
        if pb is not None and pb < 1.2 and roe > 8:
            valuation_score += 0.5

    raw_scores = {
        "行业景气度": clamp(industry_score),
        "公司竞争力": clamp(comp_score),
        "财务质量": clamp(financial_score),
        "成长确定性": clamp(growth_score),
        "估值性价比": clamp(valuation_score),
        "催化剂强度": clamp(float(catalyst)),
        "风险可控性": clamp(risk_score),
    }
    weights = weights_for(ind)
    weighted = sum(raw_scores[k] * weights.get(k, BASE_WEIGHTS[k]) for k in BASE_WEIGHTS)
    scores = [{"name": k, "score": round(v, 1), "weight": round(weights.get(k, BASE_WEIGHTS[k]) * 100, 1)} for k, v in raw_scores.items()]
    return scores, round(weighted, 1), notes, weights


def finance_trend(finance: List[Dict[str, Any]], cashflow: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    cf_by_date = {str(x.get("REPORT_DATE") or x.get("SECURITY_CODE") or i): x for i, x in enumerate(cashflow or [])}
    for i, x in enumerate(list(reversed(finance[-6:])) if len(finance) > 1 else finance):
        cf = cashflow[i] if i < len(cashflow or []) else {}
        rev_g = pct(x.get("TOTALOPERATEREVETZ"))
        np_g = pct(x.get("PARENTNETPROFITTZ"))
        tone = "good" if (np_g or 0) > 0 and (rev_g or 0) > 0 else "warn" if (np_g or 0) >= 0 else "bad"
        rows.append({
            "period": x.get("REPORT_DATE_NAME") or str(x.get("REPORT_DATE", ""))[:10] or f"周期{i+1}",
            "revenue": fmt(yi(x.get("TOTALOPERATEREVE")), "亿"),
            "profit": fmt(yi(x.get("PARENTNETPROFIT")), "亿"),
            "roe": fmt(pct(x.get("ROEJQ")), "%"),
            "cashflow": fmt(yi(first_non_none(cf.get("NETCASH_OPERATE"), cf.get("NETCASH_OPERATE_A"))), "亿"),
            "note": f"营收同比{fmt(rev_g, '%')}，净利同比{fmt(np_g, '%')}",
            "tone": tone,
        })
    return rows


def business_structure(mainop: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract top business segments from mainop data.
    
    Strategy: find the latest report date, filter MAINOP_TYPE=2 (by product),
    sort by revenue share, return top 5.
    """
    if not mainop:
        return []
    # Find latest report date
    dates = sorted(set(str(x.get("REPORT_DATE", ""))[:10] for x in mainop if x.get("REPORT_DATE")), reverse=True)
    latest_date = dates[0] if dates else None
    # Filter: MAINOP_TYPE=2 (by product/business) for latest date
    candidates = []
    for x in mainop:
        rd = str(x.get("REPORT_DATE", ""))[:10]
        mtype = str(x.get("MAINOP_TYPE", ""))
        if latest_date and rd != latest_date:
            continue
        if mtype != "2":
            continue
        candidates.append(x)
    # If no type=2, try type=1
    if not candidates:
        for x in mainop:
            rd = str(x.get("REPORT_DATE", ""))[:10]
            mtype = str(x.get("MAINOP_TYPE", ""))
            if latest_date and rd != latest_date:
                continue
            if mtype != "1":
                continue
            candidates.append(x)
    if not candidates:
        candidates = [x for x in mainop[:8]]
    out = []
    for x in candidates:
        name = first_non_none(x.get("ITEM_NAME"), x.get("PRODUCT_NAME"), x.get("BUSINESS_NAME"), x.get("MAINOP_TYPE"))
        # MBI_RATIO is 0-1 in EastMoney DataCenter; also check ZYYWSRBL (already 0-100)
        share_raw = to_float(first_non_none(x.get("MBI_RATIO"), x.get("ZYYWSRBL"), x.get("MAIN_BUSINESS_INCOME_RATIO"), x.get("INCOME_RATIO")), 0) or 0
        # If value is 0-1, convert to percentage
        share = share_raw * 100 if 0 < share_raw <= 1 else share_raw
        if not name or share <= 0.1:
            continue
        # Gross margin: GROSS_RPOFIT_RATIO is 0-1
        gm_raw = to_float(first_non_none(x.get("GROSS_RPOFIT_RATIO"), x.get("MLL"), x.get("GROSS_MARGIN")), None)
        gm = gm_raw * 100 if gm_raw is not None and 0 < abs(gm_raw) <= 1 else gm_raw
        out.append({
            "name": str(name),
            "share": round(share, 1),
            "revenue": fmt(yi(x.get("MAIN_BUSINESS_INCOME")), "亿"),
            "margin": fmt(pct(gm) if gm is not None else None, "%") if gm is not None else "—",
        })
    # Sort by share descending, take top 5
    out.sort(key=lambda r: r["share"], reverse=True)
    # Filter out tiny "其他(补充)" if more than 3 items
    if len(out) > 3:
        out = [r for r in out if not (r["share"] < 1 and "补充" in r["name"])] or out
    return out[:5]


def build_dashboard(raw: Dict[str, Any], industry_arg: str = "", catalyst_score: Optional[float] = None) -> Dict[str, Any]:
    q = quote(raw)
    qs, qt, qy = raw.get("quote_sina") or {}, raw.get("quote_tencent") or {}, raw.get("quote_yahoo") or {}
    finance = raw.get("finance") or []
    cashflow = raw.get("cashflow") or []
    ann = latest_annual(finance)
    latest = finance[0] if finance else {}
    title = first_non_none(q.get("name"), qt.get("name"), qs.get("name"), qy.get("name"), ann.get("SECURITY_NAME_ABBR"), raw.get("secucode")) or ""
    code = first_non_none(q.get("code"), qt.get("code"), raw.get("secucode", "")[:6], raw.get("yahoo_symbol"))
    price = to_float(q.get("price"))
    mkt = to_float(q.get("mktcap_yi"))
    pe = to_float(q.get("pe"))
    bps = to_float(first_non_none(latest.get("BPS"), ann.get("BPS")))
    pb = round(price / bps, 2) if price is not None and bps else None
    roe = to_float(first_non_none(ann.get("ROEJQ"), latest.get("ROEJQ")), 0) or 0
    latest_np_growth = to_float(latest.get("PARENTNETPROFITTZ"), 0) or 0
    rev_growth = to_float(ann.get("TOTALOPERATEREVETZ"), 0) or 0
    np_growth = to_float(ann.get("PARENTNETPROFITTZ"), 0) or 0
    cash_latest = to_float(first_non_none((cashflow[0] if cashflow else {}).get("NETCASH_OPERATE"), (cashflow[0] if cashflow else {}).get("NETCASH_OPERATE_A")))
    amount_yi = yi(first_non_none(qs.get("amount"), qt.get("amount")))
    _ind_field = first_non_none(latest.get("INDUSTRY"), ann.get("INDUSTRY"), raw.get("industry"))
    industry = industry_norm(industry_arg or industry_detect(str(title), str(_ind_field or "")))

    metrics_for_score = {
        "roe": roe, "np_growth": np_growth, "latest_np_growth": latest_np_growth, "rev_growth": rev_growth,
        "pb": pb, "pe": pe, "mktcap_yi": mkt, "cashflow": cash_latest, "amount_yi": amount_yi,
        "gross_margin": first_non_none(latest.get("XSMLL"), ann.get("XSMLL")),
        "rd_ratio": first_non_none(latest.get("RD_EXPENSE_RATIO"), ann.get("RD_EXPENSE_RATIO")),
        "dividend_yield": raw.get("dividend_yield"), "npl_ratio": raw.get("npl_ratio"), "nim": raw.get("nim"), "turnover": raw.get("inventory_turnover"),
    }
    scores, score, score_notes, weights = calc_scores(metrics_for_score, industry, catalyst_score)
    action = "等突破/观察" if score >= 7.2 else "观察" if score >= 6 else "谨慎观察" if score >= 4.8 else "回避/等待改善"
    risk_level = "低" if score >= 7.8 else "中" if score >= 6 else "中高" if score >= 4.8 else "高"

    kl = raw.get("kline") or []
    low20 = min([to_float(x.get("low"), 0) or 0 for x in kl[-20:]], default=None)
    high20 = max([to_float(x.get("high"), 0) or 0 for x in kl[-20:]], default=None)
    ma20 = to_float(kl[-1].get("ma20")) if kl else None
    ma60 = to_float(kl[-1].get("ma60")) if kl else None
    stop = low20
    current = price or (to_float(kl[-1].get("close")) if kl else None)
    resistance = high20 or ma60
    buy_low = stop
    buy_high = round((stop + current) / 2, 2) if stop and current else None
    confirm_low = round(max([x for x in [current, ma20, high20] if x is not None]), 2) if any(x is not None for x in [current, ma20, high20]) else None
    confirm_high = round(max([x for x in [confirm_low, ma60] if x is not None]), 2) if any(x is not None for x in [confirm_low, ma60]) else None

    price_unit = "港元" if raw.get("market_key") == "hk" else ("美元" if raw.get("market_key") == "us" else "元")
    metrics = [
        {"label": "最新价", "value": fmt(price, price_unit), "delta": f"涨跌 {fmt(pct(q.get('pct')), '%')} · 多源行情", "tone": "good" if (to_float(q.get("pct"), 0) or 0) > 0 else "warn"},
        {"label": "总市值", "value": fmt(mkt, "亿"), "delta": "市值越大通常竞争力与流动性越强", "tone": "neutral"},
        {"label": "PE / PB", "value": f"{fmt(pe)} / {fmt(pb)}", "delta": "PE看利润估值，PB看净资产估值", "tone": "good" if pb and pb < 1 else "neutral"},
        {"label": "年报营收", "value": fmt(yi(ann.get("TOTALOPERATEREVE")), "亿"), "delta": f"同比 {fmt(pct(rev_growth), '%')}", "tone": "good" if rev_growth > 0 else "warn"},
        {"label": "年报净利", "value": fmt(yi(ann.get("PARENTNETPROFIT")), "亿"), "delta": f"同比 {fmt(pct(np_growth), '%')}", "tone": "good" if np_growth > 0 else "bad"},
        {"label": "最新净利", "value": fmt(yi(latest.get("PARENTNETPROFIT")), "亿"), "delta": f"同比 {fmt(pct(latest_np_growth), '%')}", "tone": "good" if latest_np_growth > 0 else "warn"},
        {"label": "ROE", "value": fmt(pct(roe), "%"), "delta": "赚钱效率，越高越好", "tone": "good" if roe > 10 else "warn"},
        {"label": "成交额", "value": fmt(amount_yi, "亿"), "delta": "资金活跃度参考", "tone": "neutral"},
    ]

    risks = [
        {"level": "中" if latest_np_growth >= 0 else "高", "text": "最新季度利润增长放缓或波动", "mitigation": "跟踪下一季报、现金流和管理层指引。"},
        {"level": "中", "text": "行业/板块退潮会压缩估值", "mitigation": "观察板块成交额、相对强弱和政策/景气信号。"},
        {"level": "高" if stop and current and current < stop else "中", "text": "技术位跌破将削弱交易胜率", "mitigation": f"重点看{fmt(stop, price_unit)}附近是否有效跌破。"},
    ]
    if raw.get("warnings"):
        risks.insert(0, {"level": "高", "text": "数据源存在警告", "mitigation": "先核验 warnings 字段中的价格差异或异常K线。"})

    catalysts = []
    if industry == "券商":
        catalysts += ["市场成交额放大、两融活跃度提升。", "投行业务/自营收益改善。"]
    elif industry == "银行":
        catalysts += ["分红率提升与资产质量改善。", "净息差企稳。"]
    elif industry == "科技":
        catalysts += ["营收高增长、AI/云/芯片等主题催化。", "研发投入转化为商业化订单。"]
    elif industry == "制造业":
        catalysts += ["订单改善、毛利率修复、出海放量。", "库存周转好转。"]
    catalysts += ["财报改善。", "板块走强。", "成交放大。"]

    glossary = [
        {"term": "PE", "desc": "市盈率，看价格相对利润贵不贵。"},
        {"term": "PB", "desc": "市净率，券商/银行/周期股常用，看价格相对净资产贵不贵。"},
        {"term": "ROE", "desc": "净资产收益率，看公司赚钱效率。"},
        {"term": "右侧确认", "desc": "等趋势转强、突破关键位后再观察。"},
        {"term": "失效线", "desc": "跌破后原交易逻辑需要重新评估的位置。"},
    ]

    return {
        "score_version": SCORE_VERSION,
        "title": title,
        "code": code,
        "market": raw.get("market"),
        "market_key": raw.get("market_key"),
        "industry": industry,
        "date": first_non_none(qs.get("date"), q.get("date"), ""),
        "verdict": f"{title}综合评分{score}/10，当前更适合“{action}”，重点看趋势确认、行业景气和财报延续性。",
        "action": action,
        "risk_level": risk_level,
        "score": score,
        "summary": [
            f"现价约{fmt(price, price_unit)}，PE/PB约{fmt(pe)}/{fmt(pb)}。",
            f"行业识别为{industry}，评分已按行业权重自适应。",
            f"年报净利同比{fmt(pct(np_growth), '%')}，最新季度净利同比{fmt(pct(latest_np_growth), '%')}。",
            f"核心观察位：支撑{fmt(stop, price_unit)}，突破确认{fmt(confirm_low, price_unit)}。",
            "公开信息研究，不构成投资建议。",
        ],
        "metrics": metrics,
        "kline": kl,
        "signal_chart": {"current": current, "stop": stop, "buy_low": buy_low, "buy_high": buy_high, "confirm_low": confirm_low, "confirm_high": confirm_high, "resistance": resistance},
        "trade_plan": {
            "buy_left": [f"{fmt(buy_low, price_unit)}-{fmt(buy_high, price_unit)}：回踩不破可观察。", "前提：成交不放量杀跌，基本面没有新利空。", "分批观察，不做一次性重仓假设。"],
            "buy_right": [f"突破{fmt(confirm_low, price_unit)}：右侧确认。", "需要成交放大、板块共振和财报预期配合。", "若突破后快速跌回，视为假突破。"],
            "hold": [f"不有效跌破{fmt(stop, price_unit)}。", "财报没有证伪，利润/现金流未继续恶化。", "趋势维持在关键均线附近或上方。"],
            "sell": [f"冲高到{fmt(resistance, price_unit)}附近滞涨。", "跌破支撑不能收回。", "业绩低于预期或行业逻辑退潮。"],
            "stop": [f"{fmt(stop, price_unit)}有效跌破。", "利润/现金流继续恶化。", "出现公告、监管或重大经营风险。"],
            "position": ["稳健型小仓观察。", "趋势确认再考虑提高暴露。", "证伪优先降风险。"],
        },
        "scores": scores,
        "score_breakdown": scores,
        "score_notes": score_notes,
        "score_weights": weights,
        "business": business_structure(raw.get("mainop") or []),
        "finance_trend": finance_trend(finance, cashflow),
        "risks": risks,
        "catalysts": catalysts,
        "comparables": [],
        "current_compare": {"name": title, "code": code, "price": fmt(price, price_unit), "valuation": f"PE {fmt(pe)} / PB {fmt(pb)}", "score": str(score), "advantage": f"当前标的；{industry}行业适配评分", "risk": "需结合公告、财报和趋势确认", "scene": "当前标的"},
        "trackers": ["关键支撑是否守住。", "是否放量突破确认位。", "最新季度利润与现金流是否改善。", "行业景气/政策/成交额是否延续。"],
        "reevaluate": ["跌破支撑。", "财报证伪。", "板块退潮。", "数据源出现重大差异且未核验。"],
        "warnings": raw.get("warnings") or [],
        "data_sources": raw.get("data_sources"),
        "glossary": glossary,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--industry", default="", help="可选行业分类：券商/银行/科技/制造业等")
    ap.add_argument("--catalyst-score", type=float, help="AI外部传入催化剂评分 0-10")
    ap.add_argument("--comparables", default="", help='同行对比 JSON 数组字符串，如 [{"name":"XX","code":"600xxx",...}]')
    a = ap.parse_args()
    raw = json.load(open(a.input, encoding="utf-8"))
    cat = clamp(a.catalyst_score) if a.catalyst_score is not None else None
    comps = []
    if a.comparables:
        try:
            comps = json.loads(a.comparables)
        except Exception:
            pass
    dash = build_dashboard(raw, a.industry, cat)
    if comps:
        dash["comparables"] = comps
    Path(a.out).write_text(json.dumps(dash, ensure_ascii=False, indent=2), encoding="utf-8")
    print(a.out)


if __name__ == "__main__":
    main()
