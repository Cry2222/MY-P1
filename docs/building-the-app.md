# Building the APK

Three ways to turn this repository into an installable Android app, in the
order most people should try them.

**Android only.** There is no iOS build: the bot itself cannot run on iOS, so
there would be nothing for an iOS app to pair with locally.

The app is only a control surface — it needs a running bot with its control API
enabled. Building the APK does not give you a trading bot on its own.

## 1. GitHub Actions (recommended)

No toolchain to install. GitHub's runners already have the Android SDK.

**Tag a release:**

```bash
git tag v1.0.0
git push origin v1.0.0
```

The workflow builds the APK and attaches it to a GitHub Release. Download it
from the repository's Releases page on your phone and open it.

**Or build without tagging:** Actions tab → *Build Android APK* → *Run
workflow*. The APK lands as a workflow artifact, downloadable for 90 days.

That manual run takes two useful inputs:

| Input | Use it when |
|---|---|
| `cleartext_hosts` | The bot runs on a **server**. Put its Tailscale address here, e.g. `100.101.102.103`. Loopback is always allowed, so leave it empty for the on-device setup. |
| `build_type` | `release` by default. `debug` builds faster and is larger — useful when iterating. |

### Why `cleartext_hosts` matters

Android has blocked plain HTTP since API 28. The app ships a network security
config that permits cleartext **only** for the hosts baked in at build time —
loopback always, plus whatever you list. Anything else keeps Android's secure
default, so a mistyped address cannot send your API token over plain HTTP to
somewhere unintended.

If you point the app at an address that was not included, you get a clear
error naming the fix rather than a generic network failure.

### Signing

With no secrets configured, the APK is **debug-signed**. It installs and runs
perfectly well — that is the normal choice for a personal tool.

For a stable signing identity (so future builds upgrade in place), generate a
keystore once:

```bash
keytool -genkeypair -v -keystore myp1.keystore \
  -alias myp1 -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 myp1.keystore    # paste this into the secret below
```

Then add four repository secrets (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | the base64 output above |
| `ANDROID_KEYSTORE_PASSWORD` | the store password you chose |
| `ANDROID_KEY_ALIAS` | `myp1` |
| `ANDROID_KEY_PASSWORD` | the key password you chose |

**Keep the keystore file safe and backed up.** Lose it and you can never
upgrade an installed app in place again — only uninstall and reinstall.

Switching between debug-signed and release-signed also requires uninstalling
first; Android refuses to replace an app with one signed by a different key.

## 2. EAS Build (Expo's cloud)

Useful if you already have an Expo account and would rather not manage the
workflow.

```bash
npm install -g eas-cli
eas login
cd mobile
eas build --platform android --profile preview
```

`preview` produces a sideloadable APK — the only profile this project defines,
since a Play Store listing is not part of a personal tool. Profiles are in
[`mobile/eas.json`](../mobile/eas.json).

EAS manages signing keys for you, which is convenient but means the key lives
in Expo's account rather than yours.

## 3. Locally

You need the Android SDK and JDK 17. Roughly 8 GB of disk and a long first
build.

```bash
# JDK 17 and the Android command-line tools must be installed first,
# with ANDROID_HOME set.

cd mobile
npm ci
npx expo prebuild --platform android --no-install
cd android
./gradlew assembleRelease

# APK at: android/app/build/outputs/apk/release/app-release.apk
```

To include a server address:

```bash
MYP1_CLEARTEXT_HOSTS=100.101.102.103 npx expo prebuild --platform android --no-install
```

## Installing on your phone

1. Copy the `.apk` to the device, or download it there directly
2. Open it — Android will ask permission to install from this source
3. Allow it, then install

You will see a warning about an unknown developer. That is expected for any
app not distributed through the Play Store.

## About the generated `android/` directory

It is **gitignored**. `expo prebuild` recreates it from `app.json` and the
config plugins on every build, so committing it would create two sources of
truth for the same settings — and the generated copy would quietly win.

Native configuration therefore belongs in:

- `mobile/app.json` — package name, version, icons, orientation
- `mobile/plugins/` — anything the Expo config schema does not cover

`plugins/withLoopbackCleartext.js` is an example of the second case: setting
`android.usesCleartextTraffic` in `app.json` is silently ignored by current
Expo prebuild and produces no manifest attribute at all, so the plugin writes
the network security config directly.

## Troubleshooting

**"App not installed"** — an existing install is signed with a different key.
Uninstall it first.

**"Android blocked plain HTTP to this address"** — rebuild with
`cleartext_hosts` set to that host, or serve the API over HTTPS.

**Build fails on `expo prebuild`** — delete `mobile/android/` and retry;
a partially generated project does not always regenerate cleanly.

**App installs but crashes immediately** — almost always an Expo SDK version
mismatch. Run `npm run check-sdk` in `mobile/`. A native module built against
a different SDK compiles and packages fine and only fails at launch, with a
`NoClassDefFoundError` naming an Expo class. Fix with `npx expo install
<package>`; never write the version by hand.

**Gradle runs out of memory** — add to `mobile/android/gradle.properties`:
`org.gradle.jvmargs=-Xmx4g`
