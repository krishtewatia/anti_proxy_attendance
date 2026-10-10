# Production stack

`docker-compose.prod.yml` runs the system on one host. It is the file the AWS
deployment uses; this page describes the file itself, independent of where it
runs.

## Layout

```
internet ── 80/443 ──> caddy ──> frontend   (nginx, static files)
                         └─────> backend ──> vision-service
                                    └──────> MongoDB (hosted cluster)
```

| Service | Published ports | Reachable from |
|---|---|---|
| `caddy` | 80, 443 | the internet |
| `backend` | none | Caddy and the vision service |
| `frontend` | none | Caddy |
| `vision-service` | none | the backend |

Caddy obtains and renews the HTTPS certificate for `SITE_ADDRESS` from Let's
Encrypt and keeps it on the `anti_proxy_caddy_data` volume. Requests to
`/api/*` and `/health` go to the backend; everything else goes to the frontend.
No access log is written.

## How it differs from `docker-compose.yml`

| | Development | Production |
|---|---|---|
| Public entry | frontend on 3000, backend on 8000 | Caddy on 80/443 only |
| Images | built from the working tree | pulled from the registry (`IMAGE_PREFIX`, `IMAGE_TAG`) |
| Database | MongoDB container | hosted cluster via `MONGODB_URL` |
| Secrets | `.env`, with placeholders | environment only, no defaults: a missing one stops the stack |
| Database unreachable | falls back to memory when run by hand | the backend refuses to start (`REQUIRE_DATABASE=true`) |

## Settings

Required: `SITE_ADDRESS`, `IMAGE_PREFIX`, `IMAGE_TAG`, `MONGODB_URL`,
`JWT_SECRET_KEY`, `VISION_SERVICE_API_KEY`, `RECOGNITION_SIGNING_KEY`.

First start only: `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`. They
create the first administrator when none exists; that account must change its
password at first sign-in. Remove both once it exists.

Optional: `DATABASE_NAME`, `LIVENESS_MODE`, `LIVENESS_THRESHOLD`,
`REGISTRATION_RATE_LIMIT_PER_MINUTE`, and `ACME_CA` (set it to
`https://acme-staging-v02.api.letsencrypt.org/directory` for trial runs, so
rebuilding the host repeatedly does not use up the weekly limit of real
certificates).

Generate each secret freshly for the deployment; never reuse a value from a
development `.env`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Client addresses behind the proxy

Every request reaches the backend from Caddy's address, so the client's
address comes from the `X-Forwarded-For` header. That header is believed only
when the request arrived from an address in `TRUSTED_PROXY_IPS`, which the
production file sets to Caddy's fixed address on the internal network
(`172.28.0.10`). From any other peer the header is ignored. Caddy itself
discards an `X-Forwarded-For` sent by a client and writes the address it saw.
The result: rate limits and audit entries see the real client, and nobody
outside can choose the address they see.

In development `TRUSTED_PROXY_IPS` is empty and the header is always ignored.

## The browser and the API

The frontend image is built with `VITE_API_BASE_URL=same-origin`: the page
calls the API on the address it was loaded from. In development that is nginx
on port 3000, which forwards `/api/` to the backend; in production it is Caddy.
The browser never needs a separate backend port.

## Rehearsing it locally

```bash
python scripts/smoke_e2e.py --prod-rehearsal --photos /path/to/photos
```

This starts the production file with `docker/docker-compose.prod.rehearsal.yml`
on top: the same services, network and Caddy routing, with locally built
images, a throwaway in-memory MongoDB and Caddy on a loopback HTTP port. It
runs the whole end-to-end flow through Caddy and also checks that the backend,
frontend and vision service publish no port and that a made-up
`X-Forwarded-For` header does not get around the registration rate limit.
Everything is removed afterwards.
