#!/usr/bin/env python3
"""End-to-end stock dashboard generator.

Pipeline:
1) fetch quote/F10/kline
2) score dashboard JSON
3) auto-fetch peer comparables and better choices
4) run debate engine with deterministic fallback
5) render HTML
6) validate required non-empty sections

This is the preferred entrypoint for china-stock-deep-analysis to avoid partial
reports caused by missed peer/debate merge steps.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
FETCH = SCRIPT_DIR / "fetch_a_share.py"
SCORING = SCRIPT_DIR / "scoring_model.py"
PEERS = SCRIPT_DIR / "auto_comparables.py"
DEBATE = SCRIPT_DIR / "debate_engine.py"
RENDER = SCRIPT_DIR / "render_dashboard.py"


def run(cmd: List[str], *, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def code_slug(code: str) -> str:
    raw = str(code).strip().upper()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits or re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").lower()


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def merge_peer_summary(dash: Dict[str, Any], peers: Dict[str, Any]) -> None:
    comps = peers.get("comparables") or []
    dash["comparables"] = comps
    dash["better_choices"] = peers.get("better_choices") or []
    dash["peer_note"] = peers.get("peer_note")
    dash["peer_bucket"] = peers.get("bucket")
    dash["peer_errors"] = peers.get("peer_errors") or []
    if peers.get("peer_errors"):
        dash.setdefault("warnings", []).extend(["同行拉取部分失败：" + x for x in peers["peer_errors"][:3]])
    better = peers.get("better_choices") or []
    if better:
        names = "、".join(x.get("name", "") for x in better[:3] if x.get("name"))
        line = f"自动同行拉取显示：更优/更稳对照包括{names}；详见同行对比表，数据来自逐只实时行情/F10拉取。"
    elif comps:
        line = "自动同行拉取显示：暂无明显综合分更优标的，当前标的仍需结合风险与交易确认观察。"
    else:
        line = "同行自动拉取未得到有效结果，本报告已在数据可信度中标记，需人工复核。"
    summary = [s for s in (dash.get("summary") or []) if "自动同行拉取" not in str(s) and "同行里" not in str(s)]
    insert_at = max(0, len(summary) - 1)
    summary.insert(insert_at, line)
    dash["summary"] = summary


def validate_dashboard(dash: Dict[str, Any], *, quick: bool, no_debate: bool) -> List[str]:
    issues: List[str] = []
    required = ["title", "code", "score", "summary", "metrics", "kline", "trade_plan", "scores", "risks", "data_sources"]
    for k in required:
        if not dash.get(k):
            issues.append(f"missing dashboard field: {k}")
    if not quick and not dash.get("comparables"):
        issues.append("missing comparables: auto_comparables.py did not produce peer rows")
    if not no_debate:
        debate = dash.get("debate") or {}
        for k in ["votes", "direction", "confidence", "summary", "action", "key_level"]:
            if not debate.get(k):
                issues.append(f"missing debate field: {k}")
        if len(debate.get("votes") or []) < 6:
            issues.append("debate votes < 6")
    return issues


def validate_html(path: Path, *, quick: bool, no_debate: bool) -> List[str]:
    issues: List[str] = []
    if not path.exists() or path.stat().st_size <= 0:
        return [f"html missing or empty: {path}"]
    html = path.read_text(encoding="utf-8", errors="ignore")
    terms = ["总览", "K线", "买卖点", "评分", "财务", "风险", "数据可信度"]
    if not quick:
        terms.append("同行对比")
    if not no_debate:
        terms.append("多智能体博弈裁定")
    for t in terms:
        if t not in html:
            issues.append(f"html missing section text: {t}")
    return issues


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate complete China stock HTML dashboard")
    ap.add_argument("--code", required=True)
    ap.add_argument("--market", choices=["auto", "a", "hk", "us"], default="auto")
    ap.add_argument("--industry", default="")
    ap.add_argument("--catalyst-score", type=float)
    ap.add_argument("--kline-days", type=int, default=160)
    ap.add_argument("--peer-limit", type=int, default=5)
    ap.add_argument("--quick", action="store_true", help="skip full peer comparison")
    ap.add_argument("--no-debate", action="store_true")
    ap.add_argument("--work-dir", default="/root/.openclaw/workspace/stock_work")
    ap.add_argument("--out-dir", default="/root/.openclaw/workspace/outputs")
    ap.add_argument("--date", default=today_yyyymmdd())
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    work = Path(args.work_dir)
    out_dir = Path(args.out_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = code_slug(args.code)
    raw_path = work / f"{slug}_raw.json"
    dash_path = work / f"{slug}_dash.json"
    peers_path = work / f"{slug}_peers.json"
    debate_path = work / f"{slug}_debate.json"
    html_path = out_dir / f"stock_{slug}_{args.date}.html"

    run([sys.executable, str(FETCH), "--code", args.code, "--market", args.market, "--out", str(raw_path), "--kline-days", str(args.kline_days)], timeout=240)
    score_cmd = [sys.executable, str(SCORING), "--input", str(raw_path), "--out", str(dash_path)]
    if args.industry:
        score_cmd += ["--industry", args.industry]
    if args.catalyst_score is not None:
        score_cmd += ["--catalyst-score", str(args.catalyst_score)]
    run(score_cmd, timeout=120)
    dash = load_json(dash_path)

    if not args.quick:
        run([sys.executable, str(PEERS), "--input", str(raw_path), "--dashboard", str(dash_path), "--out", str(peers_path), "--limit", str(args.peer_limit)], timeout=420)
        peers = load_json(peers_path)
        merge_peer_summary(dash, peers)
        save_json(dash_path, dash)

    if not args.no_debate:
        run([sys.executable, str(DEBATE), "--input", str(dash_path), "--out", str(debate_path)], timeout=420)
        dash = load_json(dash_path)
        dash["debate"] = load_json(debate_path)
        save_json(dash_path, dash)

    issues = validate_dashboard(dash, quick=args.quick, no_debate=args.no_debate)
    if issues:
        raise RuntimeError("dashboard validation failed:\n" + "\n".join(issues))

    run([sys.executable, str(RENDER), "--input", str(dash_path), "--out-html", str(html_path)], timeout=180)
    # render_dashboard may normalize the output filename internally; prefer desired path,
    # but fall back to the normalized stock_<code>_<date>.html in out_dir.
    if not html_path.exists():
        normalized = out_dir / f"stock_{slug}_{args.date}.html"
        if normalized.exists():
            html_path = normalized
    html_issues = validate_html(html_path, quick=args.quick, no_debate=args.no_debate)
    if html_issues:
        raise RuntimeError("html validation failed:\n" + "\n".join(html_issues))

    result = {
        "ok": True,
        "code": args.code,
        "raw": str(raw_path),
        "dashboard": str(dash_path),
        "peers": str(peers_path) if peers_path.exists() else None,
        "debate": str(debate_path) if debate_path.exists() else None,
        "html": str(html_path),
        "media_line": "MEDIA:" + str(html_path),
        "comparables": len(dash.get("comparables") or []),
        "debate_fallback": bool((dash.get("debate") or {}).get("fallback")),
        "warnings": dash.get("warnings") or [],
        "peer_errors": dash.get("peer_errors") or [],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))


if __name__ == "__main__":
    main()
