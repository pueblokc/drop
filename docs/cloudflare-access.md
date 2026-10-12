# Private access with Cloudflare Tunnel + Access

Use this when you want a normal URL (`https://drop.example.com`) that works from any device,
locked to your email address. You need a domain on Cloudflare. The free Zero Trust plan is enough.

The tunnel makes an outbound connection from the Drop server, so you don't open any ports.

> **Order matters.** Create the Access application (step 1) **before** you add the public
> hostname (step 2). Otherwise the gallery is reachable without a login for a few minutes.

## 1. Access application (the lock)

Zero Trust dashboard → **Access → Applications → Add an application → Self-hosted**.

| Setting | Value |
|---|---|
| Application domain | `drop.example.com` |
| Session duration | whatever suits you (e.g. `720h` = 30 days on a phone) |
| Identity providers | **One-time PIN** (emailed code) is the easy default |
| Policy | Action **Allow**, Include → **Emails** → your address |

Don't add an `Everyone` include or a Bypass rule.

## 2. Tunnel (the pipe)

Zero Trust dashboard → **Networks → Tunnels → Create a tunnel → Cloudflared**. Name it
`drop`. Cloudflare shows an install command with a token. Run it on the Drop server:

```bash
# Debian / Ubuntu: install cloudflared from Cloudflare's apt repo or the GitHub release, then:
sudo cloudflared service install <TOKEN-FROM-THE-DASHBOARD>
```

Prefer to keep the token out of the unit's command line? Use
[`deploy/cloudflared-drop.service`](../deploy/cloudflared-drop.service) instead. It reads
`TUNNEL_TOKEN` from `/etc/cloudflared/drop.env` (mode 600).

Then add a **Public hostname** to the tunnel:

| Field | Value |
|---|---|
| Subdomain / domain | `drop` / `example.com` |
| Service | `HTTP` → `127.0.0.1:8080` |

## 3. Check it

```bash
curl -sI https://drop.example.com | head -3
```

You should get a redirect to `*.cloudflareaccess.com`, not the gallery. Open the URL on your
phone, enter the emailed code, and you're in for the session duration.

## Uploads

Uploads never go through Cloudflare. The client talks to the server over SSH, so there's
no 100 MB request limit and nothing to expose. Point `[ssh]` in the client config at the
server's LAN, VPN or Tailscale address.
