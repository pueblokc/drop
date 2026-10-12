# Private access with Tailscale

The simplest setup: only devices on your tailnet can open the gallery. No domain needed.

## On the Drop server

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 8080
tailscale serve status        # shows https://<machine>.<tailnet>.ts.net
```

`tailscale serve` proxies HTTPS on your tailnet name to the gallery on `127.0.0.1:8080`
and gets a real certificate for you. Open that URL on any device signed in to your tailnet.

## In the client config

```toml
[gallery]
url = "https://drop.your-tailnet.ts.net"

[ssh]
host = "drop"          # the MagicDNS name works for uploads too
user = "drop"
```

## Notes

- **Do not use `tailscale funnel`** for Drop. Funnel publishes to the whole internet, and the
  gallery has no login of its own.
- If you share your tailnet with other people, limit who can reach the box with a
  [Tailscale ACL / grant](https://tailscale.com/kb/1018/acls) on port 443.
- Phones need the Tailscale app on and connected. If you also want access from devices
  that aren't on the tailnet, use [Cloudflare Access](cloudflare-access.md) instead.
