from app.config import REPO_ROOT, get_settings


def test_sandbox_and_production_use_separate_databases(monkeypatch):
    monkeypatch.delenv("FM_DATABASE_PATH", raising=False)
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    assert get_settings().database_path == REPO_ROOT / "data" / "sandbox.db"
    monkeypatch.setenv("PLAID_ENV", "production")
    assert get_settings().database_path == REPO_ROOT / "data" / "finance.db"


def test_explicit_path_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("FM_DATABASE_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("PLAID_ENV", "production")
    assert get_settings().database_path == tmp_path / "x.db"
