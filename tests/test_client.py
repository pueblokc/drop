"""Tests for client/drop.py. The end-to-end test uses mode = "local" so no server is needed."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "client"))
import drop  # noqa: E402

INGEST = os.path.join(HERE, "..", "server", "drop-ingest.py").replace("\\", "/")


def write_cfg(tmp_path, extra=""):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[gallery]\nurl = "https://drop.example.com/"\nmode = "local"\n'
                   '[local]\ningest = "%s"\n%s' % (INGEST, extra), encoding="utf-8")
    return str(cfg)


def test_secret_resolution(monkeypatch):
    monkeypatch.setenv("DROP_TEST_SECRET", "s3cret")
    assert drop.secret("env:DROP_TEST_SECRET") == "s3cret"
    assert drop.secret("env:DROP_NOT_SET_ANYWHERE") == ""
    assert drop.secret("literal") == "literal"
    assert drop.secret("") == "" and drop.secret(None) == ""
    assert drop.secret("cmd:echo hi") == "hi"


def test_parse_jump():
    assert drop._parse_jump("admin@bastion.example.com:2222") == ("admin", "bastion.example.com", 2222)
    assert drop._parse_jump("bastion") == ("root", "bastion", 22)


def test_expand_skips_dotfiles(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / ".secret").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b")
    got = sorted(os.path.basename(p) for p in drop.expand([str(tmp_path), str(tmp_path / "missing")]))
    assert got == ["a.txt", "b.txt"]


def test_shipped_example_matches_init_template():
    with open(os.path.join(HERE, "..", "client", "config.example.toml"), encoding="utf-8") as f:
        assert f.read() == drop.EXAMPLE_CONFIG


def test_init_writes_example_once(tmp_path):
    path = str(tmp_path / "drop" / "config.toml")
    drop.main(["--init", "--config", path])
    assert "[gallery]" in open(path, encoding="utf-8").read()
    with pytest.raises(SystemExit):
        drop.main(["--init", "--config", path])


def test_dry_run_changes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DROP_ROOT", str(tmp_path / "root"))
    f = tmp_path / "x.txt"
    f.write_text("x")
    assert drop.main([str(f), "--dry-run", "--config", write_cfg(tmp_path)]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert not (tmp_path / "root").exists()


def test_local_end_to_end_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DROP_ROOT", str(tmp_path / "root"))
    f = tmp_path / "report.md"
    f.write_text("# hello", encoding="utf-8")
    rc = drop.main([str(f), "--title", "Hello report", "--tag", "ops", "--project", "demo",
                    "--json", "--no-notify", "--config", write_cfg(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    r = out["results"][0]
    assert r["error"] is None and r["link"] == "https://drop.example.com/#" + r["id"]
    meta = json.load(open(tmp_path / "root" / "site" / "i" / r["id"] / "meta.json", encoding="utf-8"))
    assert meta["title"] == "Hello report" and meta["tags"] == ["ops"] and meta["file"].endswith("_report.md")


def test_notify_never_prints_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DROP_TG", "123456:SUPER-SECRET-TOKEN")

    def boom(*a, **k):
        raise OSError("https://api.telegram.org/bot123456:SUPER-SECRET-TOKEN/sendMessage unreachable")
    monkeypatch.setattr(drop.urllib.request, "urlopen", boom)
    cfg = {"notify": {"telegram_token": "env:DROP_TG", "telegram_chat": "42"}}
    assert drop.notify(cfg, "hi", []) == []
    captured = capsys.readouterr()
    assert "SUPER-SECRET" not in captured.out + captured.err
