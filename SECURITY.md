# Security

## The one thing to know

**The Drop gallery has no login of its own.** nginx listens on `127.0.0.1:8080` only, and
you must put an access layer in front of it:
[Tailscale](docs/tailscale.md) or [Cloudflare Tunnel + Access](docs/cloudflare-access.md).
Don't bind it to `0.0.0.0`, don't port-forward it, and don't use `tailscale funnel`.

## How Drop is built to fail safe

- **Uploads use SSH keys only.** No upload endpoint exists over HTTP. The client never prompts
  for a password. Host keys are trusted on first use, or set `host_keys = "strict"` to only
  accept hosts already in `known_hosts`.
- **Nothing is deleted.** `drop-ingest rm` moves items to `$DROP_ROOT/trash`.
- **Uploaded HTML can't attack the gallery.** Everything under `/i/` is served with
  `Content-Security-Policy: sandbox`, which gives it an opaque origin. Reports can run their
  own scripts but can't read the gallery, its index or your session.
- **Input checks.** Stored file names are reduced to a base name (no `../`), and item ids must be
  10 hex characters before any file operation.
- **Secrets stay out of output.** Config values can come from `env:VAR` or `cmd:<command>`
  (a password manager, for example). Notification errors print only the error type, never the URL
  or token.
- **Not indexed.** Pages and files send `X-Robots-Tag: noindex, nofollow`.

## Things to decide yourself

- `[mirror] public_link = true` asks rclone for a **public** share link. Leave it off unless you
  want that.
- The SSH user only needs to write `$DROP_ROOT/inbox` and run `drop-ingest`. A dedicated
  `drop` user that owns `$DROP_ROOT` is better than `root`.
- The media volume is plain files. Back it up the way you back up anything else, or use the
  rclone mirror as the second copy.

## Reporting a problem

Please open a private
[security advisory](https://github.com/pueblokc/drop/security/advisories/new) on GitHub rather
than a public issue.
