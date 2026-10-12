"""Tests for server/drop-ingest.py, run against a temporary DROP_ROOT."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
INGEST = os.path.join(HERE, "..", "server", "drop-ingest.py")
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run(root, *args, check=True):
    env = dict(os.environ, DROP_ROOT=str(root), DROP_TITLE="Test Drops")
    p = subprocess.run([sys.executable, INGEST, *args], capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise AssertionError("drop-ingest %s failed: %s %s" % (args, p.stdout, p.stderr))
    return p


def index(root):
    with open(os.path.join(root, "site", "index.json"), encoding="utf-8") as f:
        return json.load(f)


def make_png(path, color=(30, 30, 46)):
    from PIL import Image
    Image.new("RGB", (640, 400), color).save(path)
    return str(path)


def added_id(p):
    line = [ln for ln in p.stdout.splitlines() if ln.startswith(("ADDED", "EXISTS"))][-1]
    return line.split()[1]


def test_add_image_makes_thumb_meta_and_index(tmp_path):
    src = make_png(tmp_path / "chart.png")
    p = run(tmp_path, "add", src, "--title", "Chart", "--tag", "b", "--tag", "a", "--project", "demo")
    iid = added_id(p)
    d = tmp_path / "site" / "i" / iid
    assert (d / "chart.png").exists() and (d / "thumb.jpg").exists()
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["kind"] == "image" and meta["w"] == 640 and meta["h"] == 400
    assert meta["tags"] == ["a", "b"] and meta["project"] == "demo" and meta["title"] == "Chart"
    idx = index(tmp_path)
    assert idx["title"] == "Test Drops" and [i["id"] for i in idx["items"]] == [iid]
    assert os.path.exists(src), "add without --move must keep the source"


def test_same_file_twice_is_deduplicated(tmp_path):
    src = make_png(tmp_path / "x.png")
    a = added_id(run(tmp_path, "add", src))
    p = run(tmp_path, "add", src, "--name", "other.png")
    assert p.stdout.startswith("EXISTS") and added_id(p) == a
    assert len(index(tmp_path)["items"]) == 1


def test_move_flag_consumes_upload(tmp_path):
    src = make_png(tmp_path / "up.png", (49, 50, 68))
    run(tmp_path, "add", src, "--move")
    assert not os.path.exists(src)


@pytest.mark.parametrize("bad", ["../../escape.txt", "..", ".hidden", "meta.json", "/"])
def test_name_traversal_is_neutralised_or_rejected(tmp_path, bad):
    src = tmp_path / "f.txt"
    src.write_text("hello " + bad, encoding="utf-8")
    p = run(tmp_path, "add", str(src), "--name", bad, check=False)
    # nothing may ever be written outside site/i/<id>/
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "site" / "escape.txt").exists()
    if p.returncode == 0:
        iid = added_id(p)
        stored = json.loads((tmp_path / "site" / "i" / iid / "meta.json").read_text(encoding="utf-8"))["file"]
        assert "/" not in stored and "\\" not in stored and not stored.startswith(".")
    else:
        assert "bad file name" in p.stderr


def test_text_pdf_other_get_placeholder_thumbs(tmp_path):
    for name, kind in (("notes.md", "text"), ("doc.pdf", "pdf"), ("pack.zip", "other"), ("page.html", "html")):
        f = tmp_path / name
        f.write_bytes(("content of " + name).encode())
        iid = added_id(run(tmp_path, "add", str(f)))
        meta = json.loads((tmp_path / "site" / "i" / iid / "meta.json").read_text(encoding="utf-8"))
        assert meta["kind"] == kind
        assert (tmp_path / "site" / "i" / iid / "thumb.jpg").stat().st_size > 0


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_video_gets_poster_and_duration(tmp_path):
    vid = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
                    "-t", "3", "-pix_fmt", "yuv420p", str(vid)], check=True)
    iid = added_id(run(tmp_path, "add", str(vid)))
    meta = json.loads((tmp_path / "site" / "i" / iid / "meta.json").read_text(encoding="utf-8"))
    assert meta["kind"] == "video" and meta["w"] == 320 and 2.5 <= meta["dur"] <= 3.5
    assert (tmp_path / "site" / "i" / iid / "thumb.jpg").stat().st_size > 0


def test_tag_edits_and_reindex(tmp_path):
    iid = added_id(run(tmp_path, "add", make_png(tmp_path / "t.png"), "--tag", "old"))
    run(tmp_path, "tag", iid, "--add", "new", "--remove", "old", "--title", "Renamed", "--project", "p2")
    item = index(tmp_path)["items"][0]
    assert item["tags"] == ["new"] and item["title"] == "Renamed" and item["project"] == "p2"
    os.remove(tmp_path / "site" / "index.json")
    assert "1 items" in run(tmp_path, "reindex").stdout
    assert index(tmp_path)["items"][0]["title"] == "Renamed"


def test_rm_moves_to_trash(tmp_path):
    iid = added_id(run(tmp_path, "add", make_png(tmp_path / "r.png")))
    run(tmp_path, "rm", iid)
    assert not (tmp_path / "site" / "i" / iid).exists()
    assert any(n.startswith(iid) for n in os.listdir(tmp_path / "trash"))
    assert index(tmp_path)["items"] == []


@pytest.mark.parametrize("bad", ["..", "../site", "ABCDEF1234", "abc", "0123456789a"])
def test_bad_ids_are_rejected(tmp_path, bad):
    run(tmp_path, "add", make_png(tmp_path / "keep.png"))
    for cmd in (("rm", bad), ("tag", bad, "--add", "x")):
        p = run(tmp_path, *cmd, check=False)
        assert p.returncode != 0 and "bad id" in p.stderr
    assert (tmp_path / "site" / "i").exists() and len(index(tmp_path)["items"]) == 1


def test_missing_id_is_a_clean_error(tmp_path):
    p = run(tmp_path, "tag", "0123456789", "--add", "x", check=False)
    assert p.returncode != 0 and "no such id" in p.stderr and "Traceback" not in p.stderr


def test_list_on_empty_gallery(tmp_path):
    p = run(tmp_path, "list")
    assert p.stdout == "" and index(tmp_path)["items"] == []
