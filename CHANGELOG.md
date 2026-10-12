# Changelog

## 1.0.0 (2026-10-11)

First public release. Drop has been the daily "show me" channel between an AI assistant and
its owner since September 2026. This release generalizes it for anyone to self-host.

- `drop` client: SSH/SFTP upload, `--json` output for agents, `--dry-run`, folders, tags, projects.
- Optional rclone mirror and Telegram / ntfy / webhook notifications.
- `drop-ingest` server tool: thumbnails (Pillow, ffmpeg), MP4 faststart, content-hash dedupe,
  tag / rename / trash, rebuildable index.
- Static, dark, phone-first gallery: search, filters, deep links, viewer with prev/next.
- Hardening: name and id validation, sandboxed `/i/`, loopback-only nginx.
- Debian/Ubuntu installer, Tailscale and Cloudflare Access guides, CI.
