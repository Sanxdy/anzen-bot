# Deploying the relay

`anzen_relay.py` is both ends of one protocol. The desktop runs the `agent` end (the app does this
itself from Settings → Phone → From anywhere); a public host runs the `relay` end. Neither end
opens an inbound port — both dial out — which is why this works behind a home router and from
cellular.

## Where it runs

| | |
|---|---|
| Host | `<relay-host>` — your cloud or VPS hostname/IP |
| Port | `127.0.0.1:7788` — localhost only; the reverse proxy or tunnel is the only thing that talks to it |
| Service | `anzen-relay.service` (enable it so it survives a reboot) |
| Public name | `https://<relay-hostname>` |
| Files | `<relay-dir>/{anzen_relay.py,secret,run.sh}` |

Keep the relay listener bound to localhost and publish it through a reverse proxy or tunnel that
terminates HTTPS. With cloudflared, add a hostname route to a tunnel for the host; no public relay
port is needed. The desktop and the phone still dial *out* to the relay; the proxy or tunnel only
forwards the public HTTPS endpoint to the localhost listener.

## Redeploying

```sh
HOST=relay.example.com       # replace with the relay host from the table above
RELAY_USER=ubuntu             # SSH user on that host
RELAY_DIR=/opt/anzen-relay    # directory used by the service
RELAY_PORT=7788               # must match the service and proxy/tunnel
scp relay/anzen_relay.py "$RELAY_USER@$HOST:$RELAY_DIR/anzen_relay.py"
ssh "$RELAY_USER@$HOST" "sudo systemctl restart anzen-relay && \
  curl -s -H \"X-Anzen-Relay: \$(cat '$RELAY_DIR/secret')\" \
  localhost:$RELAY_PORT/healthz"
```

`run.sh` reads the secret from `<relay-dir>/secret` (mode 600) and passes it to the relay; nothing
else does. `/healthz` takes that same secret, so the probe is the operator's and not the internet's
— an unauthenticated caller gets a 403, and cannot learn from it whether a desktop is dialled in.

## The secret

One value, in two places, and they must match or the desktop's handshake is refused:

- the desktop's data dir — `relay_secret` (`~/Library/Application Support/Anzen-bot/relay_secret`)
- the relay's — `<relay-dir>/secret`

It is minted by the app on first use. To move the relay, copy it across:

```sh
cat ~/Library/Application\ Support/Anzen-bot/relay_secret
```

Rotating it means changing both ends and restarting the relay.

## The ingress rule

A reverse proxy or tunnel must route the public hostname to the localhost listener. For
cloudflared, `/etc/cloudflared/config.yml` (root) needs one rule above the catch-all:

```yaml
  - hostname: relay.example.com
    service: http://127.0.0.1:7788
```

Create the matching DNS record with your provider; for cloudflared, use
`cloudflared tunnel route dns <tunnel-name> relay.example.com`. Keep backups of the config before
editing it.

The proxy must pass the public `Host` through untouched (cloudflared does). The relay replays it to
the desktop, and the backend compares the phone's `Origin` against that name to decide who may call
the API — a proxy that rewrites `Host` to `127.0.0.1:7788` (nginx's default `proxy_pass` does) still
serves the shell, but every write from the phone comes back 403, which reads like a wrong token.
