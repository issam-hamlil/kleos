# Kleos

Watches official football YouTube channels and republishes new highlight uploads
to a Facebook Page, an Instagram Professional account, and X.

Architecture: a single Python service on your PC, with a Cloudflare Tunnel
providing the public surface. See [Why this shape](#why-this-shape).

---

## Before you build anything

Two cheap checks decide whether this product exists. Do both before writing code
on top of this scaffold.

**1. Will the clips survive?** Post three official highlight clips by hand — one
LaLiga, one Premier League — to all three platforms. Check them 48 hours later
from a logged-out browser. Official league uploads are comprehensively
fingerprinted, and Meta's Rights Manager matches at upload time: the realistic
failure is that the API returns success and the video is muted or blocked before
anyone sees it. If they survive, build. If they do not, the same pipeline works
unchanged against club channels or lower-enforcement competitions.

**2. Can you upload video to X?** Free-tier video upload and write caps have
moved between tiers repeatedly.

```bash
python scripts/check_x_video.py path/to/short.mp4
```

It stops before tweeting unless you pass `--post`.

---

## Setup

### 1. Install

Requires Python 3.12+ and FFmpeg on `PATH`.

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put that value in `WEBSUB_SECRET`. Fill in the rest as you go — the service
starts with missing credentials and simply skips those platforms, and the status
page tells you which ones.

`YOUTUBE_CHANNEL_IDS` takes the `UC…` form, not the `@handle`. To find it, open
a channel page and read `externalId` from the source, or use the YouTube Data API.

### 3. Meta credentials

You almost certainly do **not** need App Review. A Meta app in **Development
Mode** has full API access for anyone holding a role on it, and you are posting
to your own Page and your own Instagram account.

1. Create an app at developers.facebook.com, leave it in Development Mode.
2. Add yourself as an app admin.
3. Convert the Instagram account to **Professional** and link it to the Page.
4. Generate a Page access token with `pages_manage_posts`,
   `pages_read_engagement`, `instagram_basic`, `instagram_content_publish`.
5. Exchange it for a long-lived token — short-lived tokens expire in hours.

`INSTAGRAM_USER_ID` is the IG Business account id, not the username.

### 4. The tunnel

The tunnel is load-bearing, not a convenience: **Instagram will not accept a file
upload.** It requires a publicly reachable URL and fetches the video itself. The
same tunnel serves the WebSub callback.

```bash
cloudflared tunnel --url http://localhost:8000
```

For anything beyond a first test, create a named tunnel with a stable hostname —
`PUBLIC_BASE_URL` must not change, or subscriptions break. Then put **Cloudflare
Access** in front of it, and **exclude `/media`** from the policy so Meta's
fetchers can still reach it. The app has no auth of its own by design.

### 5. Run

```bash
uvicorn kleos.main:app --host 127.0.0.1 --port 8000
```

Open `PUBLIC_BASE_URL` for the status page and kill switch. It works on a phone.

Set Windows to never sleep. If the machine is down when a highlight drops, the
push is lost for good — the catch-up poller reconciles on startup and every 15
minutes, but `STALENESS_MINUTES` stops it posting anything older than that.

---

## Why this shape

| Decision | Reason |
|---|---|
| One service, not a desktop or Android app | The UI is a job list and a button. A browser reaches it from the desk and the phone with one codebase; a native app would be a remote control for a server you still have to build. |
| Tunnel rather than cloud hosting | Instagram needs a public URL for the video. Running on the PC means no object storage and no egress bill. |
| Trim with `-c copy` | Stream copy, so a cut costs about a second regardless of length, with no re-encode and no quality loss. Keyframe-accurate is fine for a duration cap. |
| Per-platform dedupe | A failure on X must stay retryable without republishing to Facebook. |
| Staleness cutoff | The only thing standing between a PC that slept overnight and a flood of stale posts. |
| Signature verification on the callback | Otherwise the tunnel URL is an open endpoint that will publish whatever it is handed. |

## Layout

```
src/kleos/
├── main.py           startup, wiring
├── config.py         settings and credential validation
├── models.py         immutable value objects
├── db.py             dedupe ledger
├── websub.py         subscribe, verify, parse
├── pipeline.py       fetch -> trim -> publish -> record
├── scheduler.py      lease renewal, catch-up poller
├── media/            fetch (yt-dlp), trim (ffmpeg), registry (public URLs)
├── publishers/       one module per platform behind a shared Protocol
└── web/              callback endpoint, status page, media route
```

## Tests

```bash
pytest
```

Covers the logic that runs before any network call: signature verification, feed
parsing, dedupe, staleness, the kill switch, token scoping, and the pipeline's
concurrency guarantees (a video is never published twice, even under concurrent
pushes for the same upload).

## Development workflow

Every change gets its own GitHub issue and its own branch, merged to `develop`
first. `develop` only reaches `main` when its tests are green. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the exact flow.

## Scaling from here

The publisher Protocol and the pipeline stages are the stable parts. Adding real
clipping later means inserting a detector between fetch and trim — audio spike,
scorebug OCR, or an event-data API — without touching publishing. Moving off the
PC means containerising the worker; only `PUBLIC_BASE_URL` and where media is
served change.

## Rights

This republishes video you do not own. Keep `PUBLISH_ENABLED` within reach, watch
for strikes on all three accounts, and treat the kill switch as a normal part of
operating it rather than an emergency measure.
