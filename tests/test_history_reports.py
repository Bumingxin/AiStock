import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import auth
import database
import web.app as web_app
from deep_analysis.pipeline import DeepAnalysisPipeline


@pytest.fixture()
def isolated_app(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "members.db"
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(web_app, "OUTPUTS_DIR", outputs_dir)
    auth.SESSION_STORE.clear()
    database._ensure_db()
    user = database.create_user("alice", "secret", points=100)
    other = database.create_user("bob", "secret", points=100)
    session_id = auth.create_session(user)
    other_session_id = auth.create_session(other)
    client = TestClient(web_app.app)
    client.cookies.set(web_app.COOKIE_NAME, session_id)
    return client, user, other, other_session_id, outputs_dir


def test_migration_and_unified_history_store_report_metadata(isolated_app):
    _, user, _, _, _ = isolated_app
    conn = database.get_conn()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(analysis_history)")}
    finally:
        conn.close()

    assert {"report_type", "points_cost", "stock_code", "report_file", "summary_json"} <= columns

    quantitative_id = database.save_analysis(
        user_id=user["id"], title="量化报告", final_list="[]", all_reports="[]",
        market="{}", news_summary="", disclaimer="", points_cost=50,
    )
    deep_id = database.save_analysis(
        user_id=user["id"], title="深度分析_中信证券_600030", final_list="[]",
        all_reports="[]", market="{}", news_summary="", disclaimer="",
        report_type="deep", points_cost=30, stock_code="600030",
        report_file="中信证券_600030_20260714_143000_ab12cd34.html",
        summary_json=json.dumps({"score": 7.5}, ensure_ascii=False),
    )

    history = database.get_analysis_history(user["id"])
    assert [item["id"] for item in history[:2]] == [deep_id, quantitative_id]
    assert history[0]["report_type"] == "deep"
    assert history[0]["points_cost"] == 30
    assert history[0]["stock_code"] == "600030"
    assert history[1]["report_type"] == "quantitative"
    assert history[1]["points_cost"] == 50


def test_deep_history_detail_uses_owned_id_urls(isolated_app):
    client, user, _, _, outputs_dir = isolated_app
    report_file = "中信证券_600030_20260714_143000_ab12cd34.html"
    (outputs_dir / report_file).write_text("<html>report</html>", encoding="utf-8")
    history_id = database.save_analysis(
        user_id=user["id"], title="深度分析_中信证券_600030",
        final_list="[]", all_reports="[]", market="{}", news_summary="", disclaimer="",
        report_type="deep", points_cost=30, stock_code="600030",
        report_file=report_file, summary_json='{"score": 7.5}',
    )

    response = client.get(f"/api/history/{history_id}")

    assert response.status_code == 200
    detail = response.json()["detail"]
    assert detail["summary"] == {"score": 7.5}
    assert detail["view_url"] == f"/api/history/{history_id}/view"
    assert detail["download_url"] == f"/api/history/{history_id}/download"
    assert "report_file" not in detail


def test_deep_report_view_download_and_delete_enforce_ownership(isolated_app):
    client, user, _, other_session_id, outputs_dir = isolated_app
    report_file = "中信证券_600030_20260714_143000_ab12cd34.html"
    report_path = outputs_dir / report_file
    report_path.write_text("<html>owned report</html>", encoding="utf-8")
    history_id = database.save_analysis(
        user_id=user["id"], title="深度报告", final_list="[]", all_reports="[]",
        market="{}", news_summary="", disclaimer="", report_type="deep",
        report_file=report_file, summary_json="{}",
    )

    view = client.get(f"/api/history/{history_id}/view")
    download = client.get(f"/api/history/{history_id}/download")
    assert view.status_code == 200
    assert "owned report" in view.text
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]

    other_client = TestClient(web_app.app)
    other_client.cookies.set(web_app.COOKIE_NAME, other_session_id)
    assert other_client.get(f"/api/history/{history_id}/view").status_code == 404
    assert other_client.delete(f"/api/history/{history_id}").status_code == 404
    assert report_path.exists()

    deleted = client.delete(f"/api/history/{history_id}")
    assert deleted.status_code == 200
    assert not report_path.exists()
    assert database.get_analysis_detail(history_id, user["id"]) is None


def test_deep_report_rejects_unsafe_path_and_missing_file_can_be_cleaned(isolated_app):
    client, user, _, _, _ = isolated_app
    unsafe_id = database.save_analysis(
        user_id=user["id"], title="unsafe", final_list="[]", all_reports="[]",
        market="{}", news_summary="", disclaimer="", report_type="deep",
        report_file="../secret.html", summary_json="{}",
    )
    missing_id = database.save_analysis(
        user_id=user["id"], title="missing", final_list="[]", all_reports="[]",
        market="{}", news_summary="", disclaimer="", report_type="deep",
        report_file="missing.html", summary_json="{}",
    )

    assert client.get(f"/api/history/{unsafe_id}/view").status_code == 400
    assert client.delete(f"/api/history/{unsafe_id}").status_code == 400
    assert database.get_analysis_detail(unsafe_id, user["id"]) is not None

    assert client.delete(f"/api/history/{missing_id}").status_code == 200
    assert database.get_analysis_detail(missing_id, user["id"]) is None


def test_deep_pipeline_generates_unique_versioned_html_names(tmp_path):
    first = DeepAnalysisPipeline("600030", work_dir=str(tmp_path / "work"), output_dir=str(tmp_path / "out"))
    second = DeepAnalysisPipeline("600030", work_dir=str(tmp_path / "work"), output_dir=str(tmp_path / "out"))

    assert first.html_output.name != second.html_output.name
    assert first.html_output.name.endswith(".html")
    assert "600030" in first.html_output.name


def test_history_template_contains_type_and_deep_report_controls():
    template = Path("web/templates/history.html").read_text(encoding="utf-8")

    assert "报告类型" in template
    assert 'id="deep-report-frame"' in template
    assert 'id="btn-download-html"' in template
    assert "深度分析" in template

def test_legacy_filename_routes_require_report_ownership(isolated_app):
    client, user, _, other_session_id, outputs_dir = isolated_app
    report_file = "中信证券_600030_20260714_143000_ab12cd34.html"
    (outputs_dir / report_file).write_text("<html>legacy</html>", encoding="utf-8")
    database.save_analysis(
        user_id=user["id"], title="深度报告", final_list="[]", all_reports="[]",
        market="{}", news_summary="", disclaimer="", report_type="deep",
        report_file=report_file, summary_json="{}",
    )

    assert client.get(f"/api/deep-analysis/view/{report_file}").status_code == 200
    assert client.get(f"/api/deep-analysis/download/{report_file}").status_code == 200

    other_client = TestClient(web_app.app)
    other_client.cookies.set(web_app.COOKIE_NAME, other_session_id)
    assert other_client.get(f"/api/deep-analysis/view/{report_file}").status_code == 404
    assert other_client.get(f"/api/deep-analysis/download/{report_file}").status_code == 404


def test_delete_file_error_preserves_deep_history(isolated_app, monkeypatch):
    client, user, _, _, outputs_dir = isolated_app
    report_file = "locked.html"
    report_path = outputs_dir / report_file
    report_path.write_text("<html>locked</html>", encoding="utf-8")
    history_id = database.save_analysis(
        user_id=user["id"], title="locked", final_list="[]", all_reports="[]",
        market="{}", news_summary="", disclaimer="", report_type="deep",
        report_file=report_file, summary_json="{}",
    )
    original_unlink = Path.unlink

    def fail_for_report(self, *args, **kwargs):
        if self == report_path:
            raise PermissionError("locked")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_for_report)
    response = client.delete(f"/api/history/{history_id}")

    assert response.status_code == 500
    assert database.get_analysis_detail(history_id, user["id"]) is not None
    assert report_path.exists()

def test_persist_deep_report_cleans_html_when_history_save_fails(tmp_path, monkeypatch):
    html_path = tmp_path / "report.html"
    html_path.write_text("<html>report</html>", encoding="utf-8")
    summary = {"html_path": str(html_path), "html_exists": True, "title": "中信证券"}

    def fail_save(**kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(web_app, "save_analysis", fail_save)

    with pytest.raises(RuntimeError, match="database unavailable"):
        web_app._persist_deep_report(1, 30, "600030", summary)

    assert not html_path.exists()


def test_main_deep_result_uses_controlled_history_urls():
    script = Path("web/static/js/app.js").read_text(encoding="utf-8")

    assert "r.view_url" in script
    assert "r.download_url" in script