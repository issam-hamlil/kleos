# Kleos Review (Android)

Review highlights before they are published. The Kleos server fetches each new
upload and holds it; this app plays it, lets you choose which platforms to post
it to, and approves or rejects it.

Kotlin, Jetpack Compose, Material 3, Media3 ExoPlayer, WorkManager.
Min SDK 26, target SDK 35.

## Screens

- **Queue** — clips waiting for review, with duration and time left before the
  server deletes them unreviewed. Pull to refresh.
- **Review** — plays the clip, platform chips (all enabled platforms preselected),
  Approve / Reject with a confirmation, then per-platform publish results.
- **Analytics** — waiting / approved / rejected / expired totals, approval rate,
  average review time, published vs failed per platform, recent activity with
  error reasons, and whether the server's kill switch is on.
- **Settings** — server address and API token.

A background job checks the queue every 15 minutes (WorkManager's minimum) and
posts a notification when new clips arrive.

## Connect to your server

1. On the server, set `KLEOS_API_TOKEN` in `.env` (at least 24 characters) and
   keep `APPROVAL_REQUIRED=true`.
2. If Cloudflare Access protects the tunnel, exclude `/api` from the policy.
3. In the app, open **Settings**, enter the tunnel's `https://` address and the
   token, then **Save and test**.

For local testing against a server on your PC from the emulator, use
`http://10.0.2.2:8000`. Plain `http://` is refused for any other host, because
the token travels in a header on every request.

## Security

- The token is encrypted with an AES-256-GCM key held in the Android Keystore
  and never shown again after saving. It is sent only in the `Authorization`
  header — never in a URL — including for video streaming.
- Backup and device-transfer are disabled for app data.
- Cleartext traffic is blocked by the network security config except for
  localhost, `127.0.0.1` and `10.0.2.2`.

## Build

Requires JDK 17+ and the Android SDK (platform 35).

```bash
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleDebug
```

The debug APK lands in `app/build/outputs/apk/debug/`. CI builds it on every
pull request and attaches it as the `kleos-review-debug` artifact.
