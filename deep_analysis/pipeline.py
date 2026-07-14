"""Deep single-stock analysis pipeline."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

BJT = timezone(timedelta(hours=8))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"


class DeepAnalysisPipeline:
    def __init__(self, stock_code: str, market: str = "a", industry: str = "",
                 quick: bool = False, no_debate: bool = False,
                 work_dir: str = "", output_dir: str = "",
                 llm_config: Optional[Dict[str, Any]] = None):
        self.stock_code = stock_code
        self.market = market
        self.industry = industry
        self.quick = quick
        self.no_debate = no_debate
        self.llm_config = dict(llm_config or {})
        self.work_dir = Path(work_dir) if work_dir else PROJECT_ROOT / "deep_work"
        self.output_dir = Path(output_dir) if output_dir else PROJECT_ROOT / "outputs"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(BJT).strftime("%Y%m%d_%H%M%S")
        run_id = uuid.uuid4().hex[:8]
        self.raw_json = self.work_dir / f"{stock_code}_raw.json"
        self.dash_json = self.work_dir / f"{stock_code}_dash.json"
        self.peers_json = self.work_dir / f"{stock_code}_peers.json"
        self.debate_json = self.work_dir / f"{stock_code}_ai_debate.json"
        self.html_output = self.output_dir / f"{stock_code}_{date_str}_{run_id}.html"
        self._summary: Optional[Dict[str, Any]] = None

    def _run_script(self, script_name: str, args: List[str],
                    stage_cb: Optional[Callable] = None, stage_name: str = "") -> bool:
        script_path = SCRIPTS_DIR / script_name
        cmd = [sys.executable, str(script_path)] + args
        env = self._script_env(script_name)
        try:
            if stage_cb:
                stage_cb(stage_name, f"执行 {script_name}...")
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=180, cwd=str(PROJECT_ROOT), env=env)
            if result.returncode != 0:
                if stage_cb:
                    stage_cb(stage_name, f"失败: {result.stderr[:300]}", error=True)
                return False
            return True
        except subprocess.TimeoutExpired:
            if stage_cb:
                stage_cb(stage_name, f"超时: {script_name}", error=True)
            return False
        except Exception as e:
            if stage_cb:
                stage_cb(stage_name, f"异常: {e}", error=True)
            return False

    def _script_env(self, script_name: str) -> Dict[str, str]:
        env = os.environ.copy()
        if script_name == "debate_engine.py":
            api_key = str(self.llm_config.get("openai_api_key") or "").strip()
            base_url = str(self.llm_config.get("openai_base_url") or "").strip()
            model = str(self.llm_config.get("model") or "").strip()
            if api_key and api_key != "your_api_key":
                env["OPENAI_API_KEY"] = api_key
            if base_url and base_url != "http://your_base_url/v1":
                env["OPENAI_BASE_URL"] = base_url
            if model and model != "your_model_name":
                env["DEBATE_MODEL"] = model
        return env

    def _update_html_path_from_dash(self):
        """Update html_output filename using stock name from dash JSON."""
        if not self.dash_json.exists():
            return
        try:
            dash = json.loads(self.dash_json.read_text(encoding="utf-8"))
            stock_name = str(dash.get("title", "")).strip()
            if not stock_name:
                return
            date_str = datetime.now(BJT).strftime("%Y%m%d_%H%M%S")
            safe_name = stock_name.replace("/", "_").replace(chr(92), "_")
            new_path = self.output_dir / f"{safe_name}_{self.stock_code}_{date_str}_{uuid.uuid4().hex[:8]}.html"
            self.html_output = new_path
        except Exception:
            pass

    def step_fetch_data(self, stage_cb=None) -> bool:
        args = ["--code", self.stock_code, "--market", self.market, "--out", str(self.raw_json)]
        return self._run_script("fetch_a_share.py", args, stage_cb, "数据抓取")

    def step_score(self, stage_cb=None) -> bool:
        args = ["--input", str(self.raw_json), "--out", str(self.dash_json)]
        if self.industry:
            args += ["--industry", self.industry]
        return self._run_script("scoring_model.py", args, stage_cb, "评分计算")

    def step_peers(self, stage_cb=None) -> bool:
        args = ["--input", str(self.raw_json), "--out", str(self.peers_json)]
        if self.dash_json.exists():
            args += ["--dashboard", str(self.dash_json)]
        return self._run_script("auto_comparables.py", args, stage_cb, "同行对比")

    def step_merge_peers(self, stage_cb=None) -> bool:
        if not self.peers_json.exists() or not self.dash_json.exists():
            return True
        try:
            dash = json.loads(self.dash_json.read_text(encoding="utf-8"))
            peers = json.loads(self.peers_json.read_text(encoding="utf-8"))
            dash["comparables"] = peers.get("comparables", [])
            dash["better_choices"] = peers.get("better_choices", [])
            self.dash_json.write_text(json.dumps(dash, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except Exception as e:
            if stage_cb:
                stage_cb("合并同行", f"失败: {e}", error=True)
            return False

    def step_debate(self, stage_cb=None) -> bool:
        if self.no_debate:
            return True
        args = ["--input", str(self.dash_json), "--out", str(self.debate_json)]
        return self._run_script("debate_engine.py", args, stage_cb, "博弈分析")

    def step_merge_debate(self, stage_cb=None) -> bool:
        if not self.debate_json.exists() or not self.dash_json.exists():
            return True
        args = ["--dashboard", str(self.dash_json), "--debate", str(self.debate_json)]
        return self._run_script("merge_debate.py", args, stage_cb, "合并博弈")

    def step_render(self, stage_cb=None) -> bool:
        args = ["--input", str(self.dash_json), "--out-html", str(self.html_output)]
        return self._run_script("render_dashboard.py", args, stage_cb, "渲染HTML")

    def step_validate(self, stage_cb=None) -> bool:
        if not self.html_output.exists() or self.html_output.stat().st_size == 0:
            if stage_cb:
                stage_cb("验证", "HTML文件不存在或为空", error=True)
            return False
        return True

    def run(self, stage_callback: Optional[Callable] = None) -> bool:
        def cb(stage, detail, error=False):
            if stage_callback:
                stage_callback(stage, detail, error)
        steps = [
            ("数据抓取", self.step_fetch_data),
            ("评分计算", self.step_score),
            ("同行对比", self.step_peers),
            ("合并同行", self.step_merge_peers),
            ("博弈分析", self.step_debate),
            ("合并博弈", self.step_merge_debate),
            ("渲染HTML", self.step_render),
            ("验证结果", self.step_validate),
        ]
        for name, func in steps:
            cb(name, f"开始 {name}...")
            if not func(stage_cb=cb):
                cb(name, f"流水线在 '{name}' 步骤失败", error=True)
                return False
            cb(name, f"{name} 完成")
            if name == "评分计算":
                self._update_html_path_from_dash()
        self._build_summary()
        return True

    def _build_summary(self):
        summary: Dict[str, Any] = {
            "code": self.stock_code,
            "html_path": str(self.html_output),
            "html_exists": self.html_output.exists() and self.html_output.stat().st_size > 0,
        }
        if self.dash_json.exists():
            try:
                dash = json.loads(self.dash_json.read_text(encoding="utf-8"))
                summary["verdict"] = dash.get("verdict", "")
                summary["action"] = dash.get("action", "")
                summary["risk_level"] = dash.get("risk_level", "")
                summary["score"] = dash.get("score", 0)
                summary["industry"] = dash.get("industry", "")
                summary["title"] = dash.get("title", "")
                summary["market"] = dash.get("market", "")
                summary["summary_items"] = dash.get("summary", [])
                summary["metrics"] = dash.get("metrics", [])
                summary["risks"] = dash.get("risks", [])
                summary["catalysts"] = dash.get("catalysts", [])
                summary["signal_chart"] = dash.get("signal_chart", {})
                summary["trade_plan"] = dash.get("trade_plan", {})
                summary["scores"] = dash.get("scores", dash.get("score_breakdown", []))
                debate = dash.get("debate", {})
                if debate:
                    summary["debate"] = {
                        "direction": debate.get("direction", ""),
                        "confidence": debate.get("confidence", 0),
                        "summary": debate.get("summary", ""),
                        "action": debate.get("action", ""),
                        "key_level": debate.get("key_level", ""),
                        "votes": debate.get("votes", []),
                    }
            except Exception:
                pass
        self._summary = summary

    def get_summary(self) -> Dict[str, Any]:
        if self._summary is None:
            self._build_summary()
        return self._summary or {}
