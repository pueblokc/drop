#!/usr/bin/env python3
"""drop - send files to your Drop gallery in one command.

    drop report.html chart.png --title "Disk report" --tag ops --project homelab
    drop ./renders/ --tag video
    drop --init                      # write a starter config
    drop file.png --dry-run          # show what would happen

Each file is uploaded over SSH/SFTP and ingested on the server (thumbnail, metadata, index).
Optional extras: an rclone mirror (Google Drive, S3, ...) and one notification (Telegram, ntfy or a
webhook) with the links. Built for AI assistants and scripts that need a place to show you things.

Config: $DROP_CONFIG, or ~/.config/drop/config.toml (Windows: %APPDATA%/drop/config.toml).
Secret values can be literal, "env:VAR" or "cmd:<command that prints it>". Secrets are never printed.
"""
import argparse
import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

__version__ = "1.0.0"

NO_WINDOW = 0x08000000 if os.name == "nt" else 0

EXAMPLE_CONFIG = """\
# Drop client config. Docs: https://github.com/pueblokc/drop

[gallery]
url = "https://drop.example.com"      # where you open the gallery (used to build links)
mode = "ssh"                          # "ssh" = upload to a server, "local" = drop-ingest on this machine

[ssh]
host = "drop.example.lan"             # the Drop server
user = "drop"
port = 22
key = "~/.ssh/id_ed25519"             # key auth only; no password prompts
jump = ""                             # optional bastion, e.g. "root@bastion.example.com:22"
host_keys = "accept-new"              # "accept-new" (trust on first use) or "strict" (known_hosts only)
remote_inbox = "/srv/drop/inbox"
ingest = "drop-ingest"

[mirror]
rclone_remote = ""                    # e.g. "gdrive:Drops" -> also copied to gdrive:Drops/YYYY-MM/
public_link = false                   # true runs `rclone link`, which creates a PUBLIC share link

[notify]
sender = "Drop"                       # "Leo dropped 2 files"
telegram_token = ""                   # e.g. "env:DROP_TELEGRAM_TOKEN"
telegram_chat = ""                    # e.g. "env:DROP_TELEGRAM_CHAT"
ntfy_url = ""                         # e.g. "https://ntfy.sh/<long-random-topic>"
webhook_url = ""                      # POSTs JSON {"text": ..., "items": [...]}
"""


# ---------------------------------------------------------------- config
def config_path():
    if os.environ.get("DROP_CONFIG"):
        return os.path.expanduser(os.environ["DROP_CONFIG"])
    if os.name == "nt" and os.environ.get("APPDATA"):
        return os.path.join(os.environ["APPDATA"], "drop", "config.toml")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "drop", "config.toml")


def load_config(path=None):
    path = path or config_path()
    try:
        import tomllib
    except ImportError:  # Python < 3.11
        try:
            import tomli as tomllib
        except ImportError:
            sys.exit("Python 3.11+ is required (or `pip install tomli`)")
    if not os.path.exists(path):
        sys.exit("no config at %s - run `drop --init` first" % path)
    with open(path, "rb") as f:
        return tomllib.load(f)


def secret(value):
    """Resolve "env:VAR", "cmd:<command>" or a literal. Never logs the result."""
    value = (value or "").strip()
    if value.startswith("env:"):
        return os.environ.get(value[4:], "").strip()
    if value.startswith("cmd:"):
        p = subprocess.run(value[4:], shell=True, capture_output=True, text=True, creationflags=NO_WINDOW)
        return p.stdout.strip() if p.returncode == 0 else ""
    return value


# ---------------------------------------------------------------- gallery push
def _parse_jump(s):
    user, _, rest = s.rpartition("@")
    host, _, port = rest.partition(":")
    return user or "root", host, int(port or 22)


def ssh_connect(c):
    import paramiko
    key_path = os.path.expanduser(c.get("key", "~/.ssh/id_ed25519"))
    pkey = None
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            pkey = cls.from_private_key_file(key_path)
            break
        except Exception:
            continue
    if pkey is None:
        raise RuntimeError("cannot load SSH key %s (an unencrypted key or ssh-agent is expected)" % key_path)
    tofu = os.path.join(os.path.dirname(config_path()), "known_hosts")

    def client():
        cl = paramiko.SSHClient()
        cl.load_system_host_keys()
        if os.path.exists(tofu):
            cl.load_host_keys(tofu)
        if c.get("host_keys", "accept-new") == "strict":
            cl.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return cl

    def remember(cl):
        if c.get("host_keys", "accept-new") != "strict":
            os.makedirs(os.path.dirname(tofu), exist_ok=True)
            cl.save_host_keys(tofu)

    kw = dict(pkey=pkey, timeout=20, look_for_keys=False, allow_agent=True)
    host, port, user = c["host"], int(c.get("port", 22)), c.get("user", "root")
    sock, jump = None, None
    if c.get("jump"):
        ju, jh, jp = _parse_jump(c["jump"])
        jump = client()
        jump.connect(jh, jp, username=ju, **kw)
        remember(jump)
        sock = jump.get_transport().open_channel("direct-tcpip", (host, port), ("127.0.0.1", 0))
    cl = client()
    cl.connect(host, port, username=user, sock=sock, **kw)
    remember(cl)
    cl._drop_jump = jump  # keep the bastion alive with the client
    return cl


def ssh_run(cl, cmd, timeout=1800):
    _, o, e = cl.exec_command(cmd, timeout=timeout)
    out, err = o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")
    return o.channel.recv_exit_status(), out, err


def ingest_args(name, title, tags, project):
    args = ["--name", name, "--title", title]
    for t in tags:
        args += ["--tag", t]
    if project:
        args += ["--project", project]
    return args


def parse_ingest(out):
    lines = [ln for ln in out.splitlines() if ln.startswith(("ADDED", "EXISTS"))]
    if not lines:
        raise RuntimeError("unexpected ingest output: %s" % out.strip()[:200])
    return lines[-1].split()[1]


def push_ssh(cfg, cl, path, name, title, tags, project):
    s = cfg.get("ssh", {})
    remote = "%s/%d_%s" % (s.get("remote_inbox", "/srv/drop/inbox").rstrip("/"), os.getpid(), name)
    sftp = cl.open_sftp()
    try:
        sftp.put(path, remote)
    finally:
        sftp.close()
    cmd = " ".join([s.get("ingest", "drop-ingest"), "add", shlex.quote(remote), "--move"] +
                   [shlex.quote(a) for a in ingest_args(name, title, tags, project)])
    rc, out, err = ssh_run(cl, cmd)
    if rc != 0:
        ssh_run(cl, "rm -f " + shlex.quote(remote))
        raise RuntimeError("ingest failed: " + (err or out).strip()[:300])
    return parse_ingest(out)


def push_local(cfg, path, name, title, tags, project):
    exe = cfg.get("local", {}).get("ingest") or shutil.which("drop-ingest")
    cmd = ([sys.executable, exe] if exe and exe.endswith(".py") else [exe or "drop-ingest"])
    p = subprocess.run(cmd + ["add", path] + ingest_args(name, title, tags, project),
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError("ingest failed: " + (p.stderr or p.stdout).strip()[:300])
    return parse_ingest(p.stdout)


def item_link(cfg, iid):
    base = cfg.get("gallery", {}).get("url", "").rstrip("/")
    return "%s/#%s" % (base, urllib.parse.quote(iid)) if base else iid


# ---------------------------------------------------------------- mirror
def mirror(cfg, path, name, month):
    m = cfg.get("mirror", {})
    remote = m.get("rclone_remote")
    if not remote:
        return None
    dest = "%s/%s/%s" % (remote.rstrip("/"), month, name)
    p = subprocess.run(["rclone", "copyto", path, dest], capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError("rclone: " + p.stderr.strip()[:200])
    if m.get("public_link"):
        p = subprocess.run(["rclone", "link", dest], capture_output=True, text=True, creationflags=NO_WINDOW)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    return dest


# ---------------------------------------------------------------- notify
def _post(url, data, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as e:  # the URL may hold a token: print the error type only
        print("notify failed:", type(e).__name__, file=sys.stderr)
        return False


def notify(cfg, text, results):
    n = cfg.get("notify", {})
    sent = []
    tok, chat = secret(n.get("telegram_token")), secret(n.get("telegram_chat"))
    if tok and chat:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
        if _post("https://api.telegram.org/bot%s/sendMessage" % tok, data):
            sent.append("telegram")
    ntfy = secret(n.get("ntfy_url"))
    if ntfy and _post(ntfy, text.encode("utf-8"), {"Title": text.splitlines()[0]}):
        sent.append("ntfy")
    hook = secret(n.get("webhook_url"))
    if hook and _post(hook, json.dumps({"text": text, "items": results}).encode(),
                      {"Content-Type": "application/json"}):
        sent.append("webhook")
    return sent


# ---------------------------------------------------------------- main
def expand(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for f in sorted(files):
                    if not f.startswith("."):
                        yield os.path.join(root, f)
        elif os.path.isfile(p):
            yield p
        else:
            print("skip (not found):", p, file=sys.stderr)


def write_example(path):
    if os.path.exists(path):
        sys.exit("config already exists: %s" % path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(EXAMPLE_CONFIG)
    print("wrote", path, "- edit it, then: drop <file>")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="drop", description="Send files to your Drop gallery.")
    ap.add_argument("paths", nargs="*", help="files or folders")
    ap.add_argument("--title", help="title (default: file name)")
    ap.add_argument("--tag", action="append", default=[], help="tag, repeatable")
    ap.add_argument("--project", default="", help="project name for grouping")
    ap.add_argument("--no-notify", action="store_true", help="skip the notification")
    ap.add_argument("--no-mirror", action="store_true", help="skip the rclone mirror")
    ap.add_argument("--json", action="store_true", help="print results as JSON (handy for agents)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    ap.add_argument("--config", help="config file (default: %s)" % config_path())
    ap.add_argument("--init", action="store_true", help="write a starter config and exit")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    a = ap.parse_args(argv)

    if a.init:
        return write_example(a.config or config_path())
    if not a.paths:
        ap.error("give at least one file or folder")
    cfg = load_config(a.config)
    files = list(expand(a.paths))
    if not files:
        sys.exit("nothing to drop")

    today = dt.date.today()
    month = today.strftime("%Y-%m")
    mode = cfg.get("gallery", {}).get("mode", "ssh")
    if a.dry_run:
        for p in files:
            print("DRY-RUN", p, "->", mode, "as", "%s_%s" % (today.isoformat(), os.path.basename(p)),
                  "tags", a.tag, "project", a.project or "-",
                  "| mirror:", "off" if a.no_mirror else (cfg.get("mirror", {}).get("rclone_remote") or "off"))
        return 0

    cl = ssh_connect(cfg.get("ssh", {})) if mode == "ssh" else None
    results = []
    try:
        for p in files:
            base = os.path.basename(p)
            name = "%s_%s" % (today.isoformat(), base)
            title = a.title or os.path.splitext(base)[0]
            r = {"file": p, "title": title, "id": None, "link": None, "mirror": None, "error": None}
            try:
                if mode == "ssh":
                    r["id"] = push_ssh(cfg, cl, p, name, title, a.tag, a.project)
                else:
                    r["id"] = push_local(cfg, p, name, title, a.tag, a.project)
                r["link"] = item_link(cfg, r["id"])
            except Exception as e:
                r["error"] = "gallery: %s %s" % (type(e).__name__, str(e)[:200])
            if not a.no_mirror:
                try:
                    r["mirror"] = mirror(cfg, p, name, month)
                except Exception as e:
                    r["error"] = (r["error"] + "; " if r["error"] else "") + "mirror: " + str(e)[:200]
            results.append(r)
            if not a.json:
                print("OK " if r["link"] else "FAILED", base, "|", r["link"] or "-",
                      ("| mirror: " + r["mirror"]) if r["mirror"] else "", ("| " + r["error"]) if r["error"] else "")
    finally:
        if cl:
            cl.close()
            if getattr(cl, "_drop_jump", None):
                cl._drop_jump.close()

    ok = [r for r in results if r["link"]]
    sent = []
    if ok and not a.no_notify:
        sender = cfg.get("notify", {}).get("sender", "Drop")
        tags = (" #" + " #".join(a.tag)) if a.tag else ""
        body = "\n\n".join("%s%s\n%s" % (r["title"], tags, r["link"]) for r in ok)
        sent = notify(cfg, "%s dropped %d file%s\n\n%s" % (sender, len(ok), "" if len(ok) == 1 else "s", body), ok)
    if a.json:
        print(json.dumps({"results": results, "notified": sent}, indent=1))
    elif sent:
        print("notified:", ", ".join(sent))
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
