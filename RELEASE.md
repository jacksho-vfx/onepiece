# Releasing OnePiece Studio Desktop

This guide walks through every step to publish a new desktop release of OnePiece Studio. It assumes the repository is on GitHub and uses git tags like `v0.2.0`.

## 1) Update the version number
- Open the desktop app package file: `src/apps/ulti/package.json`.
- Bump the `"version"` field (for example: `0.2.0`, `0.3.0`, etc.). Stick to semantic-style versions: `MAJOR.MINOR.PATCH`.

## 2) Commit and push the version bump
Run the following commands from the repository root to capture the version change:

```bash
git status
git add .
git commit -m "Bump desktop version to v0.2.0"
git push origin main
```

## 3) Create and push the tag
- Create a tag that matches the `package.json` version:

```bash
git tag v0.2.0
```

- Push the tag to GitHub so the release can reference it:

```bash
git push origin v0.2.0
```

## 4) Build installers locally (REL-001)
Build the installers on your machine so you can upload them to GitHub Releases.

```bash
cd src/apps/ulti
npm install               # only needed the first time or after dependency changes
npm run release:prep      # builds the app and packages installers
```

The build outputs go to `src/apps/ulti/release/`, including platform-specific installers such as:
- `OnePiece Studio Desktop Setup 0.2.0.exe` (Windows)
- `OnePiece Studio Desktop-0.2.0.dmg` (macOS)
- `OnePiece Studio Desktop-0.2.0.AppImage` (Linux)

## 5) Create a GitHub release
1. Open the repository on GitHub.
2. Click **Releases** → **Draft a new release**.
3. Select the tag `v0.2.0` (create it if it is not listed yet).
4. Title the release (for example: `OnePiece Studio Desktop v0.2.0`).
5. Drag the generated `.exe`, `.dmg`, and `.AppImage` files from `src/apps/ulti/release/` into the **Attach binaries…** area.
6. Optionally mark the release as **Pre-release** for early builds.
7. Click **Publish release**.

## 6) Share the download link
Share the GitHub Releases page with teammates and users so they can download the installers: `https://github.com/<org>/<repo>/releases`.

That's it—repeat this checklist for each new desktop release.
