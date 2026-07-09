# Dashboard JSON Schema

股票 HTML 看板标准 JSON。渲染器必须尽量只依赖此结构。

## Top-level

- title: 股票名
- code: 代码
- market: 市场
- industry: 行业/主题
- date: 数据日期
- verdict: 一句话结论
- action: 当前动作：观察/等突破/谨慎持有/减仓警戒/回避
- risk_level: 低/中/高/极高
- score: 综合评分 0-10
- summary: 3-5 条短结论
- metrics: 核心数据卡
- kline: K线数组
- signal_chart: 买卖信号位
- trade_plan: 买入/持有/卖出/失效/仓位
- scores: 评分拆解
- business: 业务结构
- finance_trend / financials / financial_trend: 财务趋势表（周期、营收、净利、ROE、现金流、点评）
- risks: 风险；优先使用结构化对象，支持 level/text/mitigation
- catalysts: 催化剂
- comparables: 同行对比
- current_compare: 当前标的对比行
- data_sources: 数据可信度
- glossary: 术语小抄

## kline item

```json
{"date":"2026-05-11","open":8.24,"high":8.64,"low":8.21,"close":8.55,"volume":99892747,"ma5":8.24,"ma20":8.27,"ma60":8.65}
```

## comparable item

```json
{"name":"华泰证券","code":"601688","price":"19.37","valuation":"PE 9.97","score":"8.1","advantage":"...","risk":"...","scene":"..."}
```
