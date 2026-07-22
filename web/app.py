from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))
def _now_bjt() -> str:
    """Return current Beijing time as ISO string without tz suffix."""
    return datetime.now(BJT).replace(tzinfo=None).isoformat()
    """Return current Beijing time as ISO string without tz suffix."""
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config, save_config
from pipeline import run_pipeline, PipelineCancelled
from chat_engine import chat_analyze_stock
from auth import login_user, get_session_user, destroy_session, require_login, require_admin, check_and_deduct
from database import init_admin, create_user, list_users, get_usage_logs, add_points, delete_user, update_user_points, update_user_password, hash_password, save_analysis, get_analysis_history, get_analysis_detail, get_deep_analysis_by_file, delete_analysis, get_user_usage_logs, log_admin_action, get_admin_logs
import database
from deep_analysis import DeepAnalysisPipeline

app = FastAPI(title="AI量化选股系统")

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR.parent / "outputs"
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


MAX_PARALLEL_TASKS = 3
SESSION_TTL = 86400


class SessionState:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        self.running = False
        self.config = load_config()
        self.results: Dict[str, Any] = {}
        self.all_reports: List[Dict[str, Any]] = []
        self.market: Optional[Dict[str, Any]] = None
        self.log_ws: List[WebSocket] = []
        self.log_history: List[Dict[str, Any]] = []
        self.start_time: Optional[float] = None
        self.current_stage = 0
        self.progress = 0
        self.status_text = "就绪"
        self.stage_detail = ""
        self.counts: Dict[str, int] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.cancel_event = threading.Event()

    def add_log(self, msg: str, stage: str = "", counts: Dict[str, int] | None = None):
        entry = {
            "type": "log",
            "detail": msg,
            "stage": stage,
            "counts": counts,
            "timestamp": _now_bjt(),
        }
        self.log_history.append(entry)
        if len(self.log_history) > 2000:
            self.log_history = self.log_history[-1500:]

    def push_ws(self, message: dict):
        loop = self._loop
        if not loop or loop.is_closed():
            return
        dead = []
        for ws in self.log_ws:
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(message), loop)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.log_ws:
                self.log_ws.remove(ws)


class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, SessionState] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def create_session(self) -> SessionState:
        session_id = str(uuid.uuid4())
        session = SessionState(session_id)
        session._loop = self._loop
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        return self.sessions.get(session_id)

    def get_or_create_session(self, session_id: str) -> SessionState:
        session = self.sessions.get(session_id)
        if session is None:
            session = SessionState(session_id)
            session._loop = self._loop
            self.sessions[session_id] = session
        return session

    def remove_session(self, session_id: str):
        session = self.sessions.pop(session_id, None)
        if session and not session.cancel_event.is_set():
            session.cancel_event.set()

    def cleanup_expired(self):
        now = time.time()
        expired = [
            sid for sid, s in self.sessions.items()
            if not s.running and (now - s.created_at) > SESSION_TTL
        ]
        for sid in expired:
            self.remove_session(sid)

    def active_task_count(self) -> int:
        return sum(1 for s in self.sessions.values() if s.running)


manager = SessionManager()


class DeepAnalysisState:
    def __init__(self):
        self.running = False
        self.stock_code = ""
        self.market = "a"
        self.industry = ""
        self.quick = False
        self.no_debate = False
        self.cancel_event = threading.Event()
        self.log_ws: List[WebSocket] = []
        self.log_history: List[Dict[str, Any]] = []
        self.progress = 0
        self.status_text = "就绪"
        self.current_stage = ""
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None

    def add_log(self, msg: str, stage: str = ""):
        entry = {"type": "log", "detail": msg, "stage": stage, "timestamp": _now_bjt()}
        self.log_history.append(entry)
        if len(self.log_history) > 500:
            self.log_history = self.log_history[-400:]

    def push_ws(self, message: dict):
        loop = manager._loop
        if not loop or loop.is_closed():
            return
        dead = []
        for ws in self.log_ws:
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(message), loop)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.log_ws:
                self.log_ws.remove(ws)


deep_analysis_state = DeepAnalysisState()

COOKIE_NAME = "session_id"


def _deep_report_path(report_file: str) -> Optional[Path]:
    """Resolve a stored deep-report filename inside the outputs directory."""
    if not report_file or Path(report_file).name != report_file or not report_file.lower().endswith(".html"):
        return None
    root = OUTPUTS_DIR.resolve()
    candidate = (root / report_file).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate

def _persist_deep_report(user_id: int, points_cost: int, stock_code: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    """Save a completed deep report and return its public result payload."""
    html_path = Path(summary.get("html_path", ""))
    report_file = html_path.name
    stored_summary = dict(summary)
    stored_summary.pop("html_path", None)
    title_name = summary.get("title") or stock_code
    try:
        history_id = save_analysis(
            user_id=user_id,
            title=f"深度分析_{title_name}_{stock_code}",
            final_list="[]",
            all_reports="[]",
            market=json.dumps({"market": summary.get("market", "")}, ensure_ascii=False),
            news_summary="",
            disclaimer="",
            report_type="deep",
            points_cost=points_cost,
            stock_code=stock_code,
            report_file=report_file,
            summary_json=json.dumps(stored_summary, ensure_ascii=False),
        )
    except Exception:
        if html_path.is_file():
            html_path.unlink()
        raise
    public_summary = dict(summary)
    public_summary.pop("html_path", None)
    public_summary["html_exists"] = html_path.is_file() and html_path.stat().st_size > 0
    public_summary["history_id"] = history_id
    public_summary["view_url"] = f"/api/history/{history_id}/view"
    public_summary["download_url"] = f"/api/history/{history_id}/download"
    return public_summary

def _resolve_session(request: Request, response=None) -> SessionState:
    session_id = request.cookies.get(COOKIE_NAME)
    session = manager.get_or_create_session(session_id)
    if response and session.session_id != session_id:
        response.set_cookie(COOKIE_NAME, session.session_id, max_age=SESSION_TTL, httponly=False, samesite="Lax")
    return session


@app.on_event("startup")
async def save_loop():
    manager._loop = asyncio.get_event_loop()
    init_admin()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = require_login(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "index.html", {"user": user, "active_page": "monitor", "show_runtime": True})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session_id = request.cookies.get(COOKIE_NAME)
    user = get_session_user(session_id)
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    session_id = login_user(username, password)
    if session_id is None:
        return templates.TemplateResponse(request, "login.html", {"error": "用户名或密码错误"})
    user = get_session_user(session_id)
    redirect_url = "/admin" if user and user.get("is_admin") else "/"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(COOKIE_NAME, session_id, max_age=SESSION_TTL, httponly=False, samesite="Lax")
    return response


@app.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        destroy_session(session_id)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/api/config")
async def get_config(request: Request):
    session = _resolve_session(request)
    cfg = dict(session.config)
    if cfg.get("openai_api_key"):
        cfg["openai_api_key"] = cfg["openai_api_key"][:8] + "****"
    return cfg


@app.post("/api/config")
async def save_config_api(request: Request):
    data = await request.json()
    int_keys = {
        "top_sectors", "top_stocks", "min_per_sector", "max_per_sector",
        "news_per_source", "news_workers", "stock_workers", "news_total_limit",
    }
    for key in int_keys:
        if key in data:
            try:
                data[key] = int(data[key])
            except (ValueError, TypeError):
                pass
    session = _resolve_session(request)
    session.config.update(data)
    save_config(session.config)
    return {"message": "设置已保存"}


@app.get("/api/status")
async def get_status(request: Request):
    session = _resolve_session(request)
    elapsed = 0
    if session.start_time:
        elapsed = int(time.time() - session.start_time)
    return {
        "running": session.running,
        "progress": session.progress,
        "stage": session.current_stage,
        "status": session.status_text,
        "elapsed": elapsed,
        "stage_detail": session.stage_detail,
        "counts": session.counts,
    }


@app.get("/api/logs")
async def get_logs(request: Request):
    session = _resolve_session(request)
    return {"logs": session.log_history[-500:]}


@app.post("/api/analyze")
async def start_analysis(request: Request):
    session = _resolve_session(request)
    if session.running:
        return JSONResponse({"error": "任务已在运行中"}, status_code=409)

    if manager.active_task_count() >= MAX_PARALLEL_TASKS:
        return JSONResponse({"error": f"系统最多同时运行 {MAX_PARALLEL_TASKS} 个任务，请稍后重试"}, status_code=429)

    session.config = load_config()

    if not session.config.get("openai_api_key") or session.config["openai_api_key"] == "your_api_key":
        return JSONResponse({"error": "请先配置 API Key"}, status_code=400)

    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "请先登录"}, status_code=401)
    if not check_and_deduct(user["id"], "analysis", session.config, detail="启动分析任务", is_admin=user["is_admin"]):
        return JSONResponse({"error": f"点数不足，请联系管理员充值（本次分析需要 {session.config.get('analysis_points_cost', 1)} 点）"}, status_code=402)

    analysis_user_id = user["id"]
    analysis_points_cost = int(session.config.get("analysis_points_cost", 1))

    session.cancel_event.clear()
    session.running = True
    session.start_time = time.time()
    session.progress = 0
    session.current_stage = 0
    session.status_text = "运行中..."
    session.log_history = []

    def stage_cb(stage: str, detail: str, counts: dict | None = None):
        msg = {"type": "log", "detail": detail, "stage": stage, "counts": counts, "timestamp": _now_bjt()}
        session.add_log(detail, stage, counts)
        session.push_ws(msg)

        if stage == "news_fetching":
            session.current_stage = 1
            session.status_text = "抓取新闻..."
            session.progress = 5
        elif stage in ("news_done", "llm_sector"):
            session.current_stage = 2
            session.status_text = "LLM分析中..."
            session.progress = 18
        elif stage == "sector_done":
            session.current_stage = 3
            session.status_text = "构建候选池..."
            session.progress = 34
        elif stage in ("pool_done", "stock_progress"):
            session.current_stage = 4
            session.progress = 55
        elif stage == "stock_done":
            session.current_stage = 5
            session.status_text = "综合排序..."
            session.progress = 78
        elif stage == "final_done":
            session.current_stage = 6
            session.status_text = "完成"
            session.progress = 100

        if counts:
            session.counts.update(counts)

        session.push_ws({"type": "progress", "stage": session.current_stage, "progress": session.progress, "status": session.status_text})

    def worker():
        try:
            result = run_pipeline(session.config, stage_cb=stage_cb, cancel_event=session.cancel_event)
            all_reports = result.pop("all_reports", []) if isinstance(result, dict) else []
            market = result.pop("_market", None) if isinstance(result, dict) else None
            session.results = result
            session.all_reports = all_reports
            session.market = market
            title = f"量化分析报告_{datetime.now(BJT).strftime('%Y%m%d')}"
            history_id = save_analysis(
                user_id=analysis_user_id,
                title=title,
                final_list=json.dumps(result.get("final_list", []), ensure_ascii=False),
                all_reports=json.dumps(all_reports, ensure_ascii=False),
                market=json.dumps(market or {}, ensure_ascii=False),
                news_summary="",
                disclaimer=result.get("disclaimer", ""),
                points_cost=analysis_points_cost,
            )
            result["history_id"] = history_id
            session.push_ws({"type": "done", "result": result})
        except PipelineCancelled:
            session.progress = 0
            session.status_text = "已停止"
            session.push_ws({"type": "cancelled", "detail": "用户取消了分析任务"})
            session.add_log("用户取消了分析任务", "cancelled")
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            session.push_ws({"type": "error", "detail": str(exc), "traceback": tb})
            session.add_log(f"运行异常：{exc}", "error")
        finally:
            session.running = False
            if not session.cancel_event.is_set():
                session.status_text = "完成" if session.progress >= 100 else "异常终止"
            session.push_ws({"type": "progress", "stage": session.current_stage, "progress": session.progress, "status": session.status_text})

    threading.Thread(target=worker, daemon=True).start()
    return {"message": "分析任务已启动"}


@app.post("/api/stop")
async def stop_analysis(request: Request):
    session = _resolve_session(request)
    if not session.running:
        return JSONResponse({"error": "没有正在运行的任务"}, status_code=409)

    session.cancel_event.set()
    session.running = False
    session.progress = 0
    session.current_stage = 0
    session.status_text = "已停止"
    session.push_ws({"type": "cancelled", "detail": "用户取消了分析任务"})
    session.push_ws({"type": "progress", "stage": 0, "progress": 0, "status": "已停止"})
    return {"message": "已发送停止信号"}


@app.get("/api/results")
async def get_results(request: Request):
    session = _resolve_session(request)
    return {
        "results": session.results,
        "market": session.market,
    }


@app.post("/api/chat")
async def chat_api(request: Request):
    data = await request.json()
    stock = data.get("stock", {})
    history = data.get("history", [])
    question = data.get("question", "")

    if not question:
        return JSONResponse({"error": "请输入问题"}, status_code=400)

    session = _resolve_session(request)

    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "请先登录"}, status_code=401)
    if not check_and_deduct(user["id"], "chat", session.config, detail=f"聊天问答: {question[:50]}", is_admin=user["is_admin"]):
        return JSONResponse({"error": f"点数不足，请联系管理员充值（每次问答需要 {session.config.get('chat_points_cost', 1)} 点）"}, status_code=402)

    try:
        answer = chat_analyze_stock(stock, history, session.config)
        return {"answer": answer}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/user/info")
async def get_user_info(request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "未登录"}, status_code=401)
    return {
        "username": user.get("username", ""),
        "nickname": user.get("nickname") or user.get("username", ""),
        "points": user.get("points", 0),
        "is_admin": user.get("is_admin", False),
    }


@app.post("/api/user/nickname")
async def change_nickname(request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "未登录"}, status_code=401)
    data = await request.json()
    nickname = data.get("nickname", "").strip()
    if not nickname:
        return JSONResponse({"error": "昵称不能为空"}, status_code=400)
    conn = database.get_conn()
    try:
        conn.execute("UPDATE users SET nickname = ? WHERE id = ?", (nickname, user["id"]))
        conn.commit()
    finally:
        conn.close()
    return {"message": "昵称已修改"}


@app.post("/api/user/password")
async def change_password(request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "未登录"}, status_code=401)
    data = await request.json()
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")
    if not old_password or not new_password:
        return JSONResponse({"error": "请填写完整"}, status_code=400)
    if len(new_password) < 4:
        return JSONResponse({"error": "新密码至少4位"}, status_code=400)
    conn = database.get_conn()
    try:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row or row["password_hash"] != hash_password(old_password):
            return JSONResponse({"error": "当前密码错误"}, status_code=400)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user["id"]))
        conn.commit()
    finally:
        conn.close()
    return {"message": "密码已修改"}


@app.get("/api/user/usage-logs")
async def get_usage_logs_api(request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "未登录"}, status_code=401)
    logs = get_user_usage_logs(user["id"], limit=200)
    return {"logs": logs}


@app.get("/api/history")
async def get_history_list(request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "未登录"}, status_code=401)
    return {"history": get_analysis_history(user["id"])}


@app.get("/api/history/{history_id}/view")
async def view_history_report(history_id: int, request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "未登录"}, status_code=401)
    detail = get_analysis_detail(history_id, user["id"])
    if not detail or detail.get("report_type") != "deep":
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    file_path = _deep_report_path(detail.get("report_file", ""))
    if file_path is None:
        return JSONResponse({"error": "无效报告路径"}, status_code=400)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(str(file_path), media_type="text/html")


@app.get("/api/history/{history_id}/download")
async def download_history_report(history_id: int, request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "未登录"}, status_code=401)
    detail = get_analysis_detail(history_id, user["id"])
    if not detail or detail.get("report_type") != "deep":
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    file_path = _deep_report_path(detail.get("report_file", ""))
    if file_path is None:
        return JSONResponse({"error": "无效报告路径"}, status_code=400)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(
        str(file_path), media_type="text/html", filename=detail["report_file"]
    )


@app.get("/api/history/{history_id}")
async def get_history_detail(history_id: int, request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "未登录"}, status_code=401)
    detail = get_analysis_detail(history_id, user["id"])
    if not detail:
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    detail["report_type"] = detail.get("report_type") or "quantitative"
    if detail["report_type"] == "deep":
        try:
            summary = json.loads(detail.get("summary_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            summary = {}
        public_detail = {
            "id": detail["id"],
            "created_at": detail["created_at"],
            "title": detail.get("title", ""),
            "report_type": "deep",
            "points_cost": detail.get("points_cost", 0),
            "stock_code": detail.get("stock_code", ""),
            "summary": summary,
            "view_url": f"/api/history/{history_id}/view",
            "download_url": f"/api/history/{history_id}/download",
        }
        return {"detail": public_detail}
    return {"detail": detail}


@app.delete("/api/history/{history_id}")
async def delete_history_item(history_id: int, request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "未登录"}, status_code=401)
    detail = get_analysis_detail(history_id, user["id"])
    if not detail:
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    if (detail.get("report_type") or "quantitative") == "deep":
        file_path = _deep_report_path(detail.get("report_file", ""))
        if file_path is None:
            return JSONResponse({"error": "无效报告路径"}, status_code=400)
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError as exc:
                return JSONResponse({"error": f"删除报告文件失败：{exc}"}, status_code=500)
    delete_analysis(history_id, user["id"])
    return {"message": "已删除"}


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    user = require_login(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "history.html", {"user": user, "active_page": "history", "show_runtime": True})


@app.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    user = require_login(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "billing.html", {"user": user, "active_page": "billing", "show_runtime": True})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    user = require_admin(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    users = list_users()
    for u in users:
        u["role"] = "admin" if u.get("is_admin") else "user"
    conn = database.get_conn()
    try:
        rows = conn.execute(
            """
            SELECT l.*, u.username
            FROM usage_logs l
            JOIN users u ON l.user_id = u.id
            ORDER BY l.created_at DESC
            LIMIT 200
            """
        ).fetchall()
        logs = [dict(r) for r in rows]
        for log in logs:
            log["time"] = log["created_at"]
    finally:
        conn.close()
    cfg = load_config()
    admin_logs = get_admin_logs()
    return templates.TemplateResponse(request, "admin.html", {
        "users": users,
        "logs": logs,
        "admin_logs": admin_logs,
        "config": cfg,
    })


@app.post("/admin/config")
async def admin_config(request: Request):
    user = require_admin(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    form = await request.form()
    analysis_points_cost = int(form.get("analysis_points_cost", 1))
    chat_points_cost = int(form.get("chat_points_cost", 1))
    deep_analysis_points_cost = int(form.get("deep_analysis_points_cost", 30))
    cfg = load_config()
    old_analysis = cfg.get("analysis_points_cost", 1)
    old_chat = cfg.get("chat_points_cost", 1)
    old_deep = cfg.get("deep_analysis_points_cost", 30)
    cfg["analysis_points_cost"] = analysis_points_cost
    cfg["chat_points_cost"] = chat_points_cost
    cfg["deep_analysis_points_cost"] = deep_analysis_points_cost
    save_config(cfg)
    log_admin_action(user["username"], "config_change", "", f"分析扣费: {old_analysis}->{analysis_points_cost}, 对话扣费: {old_chat}->{chat_points_cost}, 深度分析扣费: {old_deep}->{deep_analysis_points_cost}")
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/admin/config/save")
async def admin_config_save(request: Request):
    user = require_admin(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    data = await request.json()
    int_keys = {
        "top_sectors", "top_stocks", "min_per_sector", "max_per_sector",
        "news_per_source", "news_workers", "stock_workers", "news_total_limit",
        "analysis_points_cost", "chat_points_cost", "deep_analysis_points_cost", "default_user_points",
    }
    for key in int_keys:
        if key in data:
            try:
                data[key] = int(data[key])
            except (ValueError, TypeError):
                pass
    if "enable_realtime_news" in data:
        data["enable_realtime_news"] = bool(data["enable_realtime_news"])
    if "enable_anysearch" in data:
        data["enable_anysearch"] = bool(data["enable_anysearch"])
    cfg = load_config()
    old_cfg = dict(cfg)
    cfg.update(data)
    save_config(cfg)
    changes = []
    for key in data:
        if key in old_cfg and old_cfg[key] != cfg[key]:
            changes.append(f"{key}: {old_cfg[key]} -> {cfg[key]}")
    log_admin_action(user["username"], "config_change", "", f"系统配置变更: {'; '.join(changes[:10])}")
    return {"message": "配置已保存"}


@app.post("/admin/config/reset")
async def admin_config_reset(request: Request):
    user = require_admin(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    from config import DEFAULT
    cfg = dict(DEFAULT)
    save_config(cfg)
    log_admin_action(user["username"], "config_change", "", "恢复默认系统配置")
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/admin/users/create")
async def admin_create_user(request: Request):
    user = require_admin(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    points = int(form.get("points", 10))
    if username and password:
        create_user(username, password, points)
        log_admin_action(user["username"], "create_user", username, f"创建用户，初始点数: {points}")
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/admin/users/{user_id}/add-points")
async def admin_add_points(user_id: int, request: Request):
    user = require_admin(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    form = await request.form()
    points = int(form.get("points", 0))
    if points > 0:
        add_points(user_id, points)
        target = database.get_user_by_id(user_id)
        target_name = target["username"] if target else str(user_id)
        log_admin_action(user["username"], "add_points", target_name, f"充值 {points} 点")
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/admin/users/{user_id}/delete")
async def admin_delete_user(user_id: int, request: Request):
    user = require_admin(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    if user["id"] == user_id:
        return RedirectResponse(url="/admin", status_code=302)
    target = database.get_user_by_id(user_id)
    target_name = target["username"] if target else str(user_id)
    delete_user(user_id)
    log_admin_action(user["username"], "delete_user", target_name, f"删除用户")
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/admin/users/{user_id}/change-password")
async def admin_change_password(user_id: int, request: Request):
    user = require_admin(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    form = await request.form()
    new_password = form.get("new_password", "")
    if not new_password or len(new_password) < 4:
        return RedirectResponse(url="/admin", status_code=302)
    target = database.get_user_by_id(user_id)
    target_name = target["username"] if target else str(user_id)
    update_user_password(user_id, new_password)
    log_admin_action(user["username"], "change_password", target_name, f"修改密码")
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/admin/users/{user_id}/set-points")
async def admin_set_points(user_id: int, request: Request):
    user = require_admin(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    form = await request.form()
    points = int(form.get("points", 0))
    if points >= 0:
        target = database.get_user_by_id(user_id)
        target_name = target["username"] if target else str(user_id)
        old_points = target["points"] if target else 0
        update_user_points(user_id, points)
        log_admin_action(user["username"], "set_points", target_name, f"修改点数: {old_points} -> {points}")
    return RedirectResponse(url="/admin", status_code=302)



# ─── Deep Analysis API ───────────────────────────────────────────

@app.post("/api/deep-analysis/start")
async def start_deep_analysis(request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "请先登录"}, status_code=401)

    state = deep_analysis_state
    if state.running:
        return JSONResponse({"error": "深度分析任务已在运行中"}, status_code=409)

    body = await request.json()
    stock_code = (body.get("code") or "").strip()
    market = "auto"
    industry = ""
    quick = bool(body.get("quick", False))
    no_debate = bool(body.get("no_debate", False))

    if not stock_code:
        return JSONResponse({"error": "请输入股票代码"}, status_code=400)

    cfg = load_config()
    if not check_and_deduct(user["id"], "deep_analysis", cfg, detail=f"深度分析 {stock_code}", is_admin=user["is_admin"]):
        cost = cfg.get("deep_analysis_points_cost", 30)
        return JSONResponse({"error": f"点数不足（本次需要 {cost} 点）"}, status_code=402)

    deep_user_id = user["id"]
    deep_points_cost = int(cfg.get("deep_analysis_points_cost", 30))

    state.running = True
    state.stock_code = stock_code
    state.market = market
    state.industry = industry
    state.quick = quick
    state.no_debate = no_debate
    state.cancel_event.clear()
    state.progress = 0
    state.status_text = "运行中..."
    state.current_stage = ""
    state.result = None
    state.error = None
    state.log_history = []

    def stage_cb(stage: str, detail: str, error: bool = False):
        state.current_stage = stage
        state.add_log(detail, stage)
        msg = {"type": "log", "detail": detail, "stage": stage, "timestamp": _now_bjt()}
        state.push_ws(msg)

        stages = ["数据抓取", "评分计算", "同行对比", "合并同行", "博弈分析", "合并博弈", "渲染HTML", "验证结果"]
        try:
            idx = stages.index(stage)
            state.progress = int((idx + 1) / len(stages) * 100)
        except ValueError:
            pass
        state.push_ws({"type": "progress", "stage": state.current_stage, "progress": state.progress, "status": state.status_text})

    def worker():
        try:
            cfg = load_config()
            pipeline = DeepAnalysisPipeline(
                stock_code=stock_code,
                market=market,
                industry=industry,
                quick=quick,
                no_debate=no_debate,
                llm_config=cfg,
            )
            success = pipeline.run(stage_callback=stage_cb)
            if state.cancel_event.is_set():
                state.status_text = "已取消"
                state.push_ws({"type": "cancelled", "detail": "用户取消了深度分析"})
                return

            if success:
                state.result = _persist_deep_report(
                    deep_user_id, deep_points_cost, stock_code, pipeline.get_summary()
                )
                state.status_text = "完成"
                state.progress = 100
                state.push_ws({"type": "done", "result": state.result})
            else:
                state.error = "流水线执行失败"
                state.status_text = "失败"
                state.push_ws({"type": "error", "detail": "流水线执行失败，请查看日志"})
        except Exception as exc:
            import traceback
            state.error = str(exc)
            state.status_text = "异常"
            state.push_ws({"type": "error", "detail": str(exc), "traceback": traceback.format_exc()})
        finally:
            state.running = False
            state.push_ws({"type": "progress", "stage": state.current_stage, "progress": state.progress, "status": state.status_text})

    threading.Thread(target=worker, daemon=True).start()
    return {"message": f"深度分析 {stock_code} 已启动"}


@app.post("/api/deep-analysis/stop")
async def stop_deep_analysis(request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "请先登录"}, status_code=401)
    state = deep_analysis_state
    if not state.running:
        return JSONResponse({"error": "没有正在运行的深度分析任务"}, status_code=409)
    state.cancel_event.set()
    state.running = False
    state.status_text = "已停止"
    state.push_ws({"type": "cancelled", "detail": "用户取消了深度分析"})
    return {"message": "已发送停止信号"}


@app.get("/api/deep-analysis/status")
async def deep_analysis_status(request: Request):
    state = deep_analysis_state
    return {
        "running": state.running,
        "stock_code": state.stock_code,
        "market": state.market,
        "progress": state.progress,
        "status_text": state.status_text,
        "current_stage": state.current_stage,
        "result": state.result,
        "error": state.error,
    }


@app.get("/api/deep-analysis/download/{filename}")
async def deep_analysis_download(filename: str, request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "请先登录"}, status_code=401)
    detail = get_deep_analysis_by_file(filename, user["id"])
    if not detail:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    file_path = _deep_report_path(detail.get("report_file", ""))
    if file_path is None:
        return JSONResponse({"error": "无效文件名"}, status_code=400)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(str(file_path), media_type="text/html", filename=filename)


@app.get("/api/deep-analysis/view/{filename}")
async def deep_analysis_view(filename: str, request: Request):
    user = require_login(request)
    if user is None:
        return JSONResponse({"error": "请先登录"}, status_code=401)
    detail = get_deep_analysis_by_file(filename, user["id"])
    if not detail:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    file_path = _deep_report_path(detail.get("report_file", ""))
    if file_path is None:
        return JSONResponse({"error": "无效文件名"}, status_code=400)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(str(file_path), media_type="text/html")


@app.websocket("/ws/deep-logs")
async def websocket_deep_logs(websocket: WebSocket):
    await websocket.accept()
    session_id = websocket.cookies.get(COOKIE_NAME) or websocket.query_params.get("session_id")
    state = deep_analysis_state
    state.log_ws.append(websocket)
    try:
        for entry in state.log_history[-200:]:
            await websocket.send_json(entry)
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in state.log_ws:
            state.log_ws.remove(websocket)


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    session_id = websocket.cookies.get(COOKIE_NAME) or websocket.query_params.get("session_id")
    session = manager.get_or_create_session(session_id)
    session.log_ws.append(websocket)
    try:
        for entry in session.log_history[-200:]:
            await websocket.send_json(entry)
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in session.log_ws:
            session.log_ws.remove(websocket)

