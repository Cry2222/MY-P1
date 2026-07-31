#!/usr/bin/env python3
"""Point the generated Android project's release build at a real keystore.

`expo prebuild` wires the release buildType to the *debug* signing config,
which is fine for a sideloaded personal build but means every release APK is
signed with a well-known key. When a keystore is supplied, this rewrites the
generated `android/app/build.gradle` to use it.

The generated project is disposable — it is recreated by prebuild on every
build and is gitignored — so patching it here is the right layer. Nothing in
the app's source needs to know about signing.

    python3 scripts/configure-release-signing.py android/app/build.gradle

Reads the credentials from gradle.properties at build time, so no secret ever
enters this file or the repository.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RELEASE_CONFIG = """signingConfigs {
        release {
            storeFile file(MYP1_UPLOAD_STORE_FILE)
            storePassword MYP1_UPLOAD_STORE_PASSWORD
            keyAlias MYP1_UPLOAD_KEY_ALIAS
            keyPassword MYP1_UPLOAD_KEY_PASSWORD
        }"""

# Matches the release buildType's signingConfig line specifically, so the
# debug buildType keeps pointing at the debug key.
RELEASE_BUILDTYPE = re.compile(
    r"(buildTypes\s*\{[\s\S]*?release\s*\{[\s\S]*?)signingConfig signingConfigs\.debug"
)


def configure(path: Path) -> None:
    source = path.read_text()

    if "signingConfigs.release" in source:
        print(f"{path}: release signing already configured")
        return

    if "signingConfigs {" not in source:
        raise SystemExit(f"{path}: no signingConfigs block found — unexpected template")

    patched = source.replace("signingConfigs {", RELEASE_CONFIG, 1)

    patched, count = RELEASE_BUILDTYPE.subn(
        r"\1signingConfig signingConfigs.release", patched, count=1
    )
    if count != 1:
        raise SystemExit(
            f"{path}: could not repoint the release buildType — template changed"
        )

    path.write_text(patched)
    print(f"{path}: release signing configured")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <path to android/app/build.gradle>")
    configure(Path(sys.argv[1]))
