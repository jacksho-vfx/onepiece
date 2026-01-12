# Releasing OnePiece Studio Desktop

Follow this checklist to ship a new OnePiece Studio Desktop build from the `src/apps/ulti` package. Each step keeps the version, tag, and generated installers in sync so GitHub Releases stays trustworthy.

## Prerequisites
- Node.js 18+ with npm available.
- Clean working tree (`git status` shows no pending changes).
- Ability to push commits and tags to the repository remote.

## 1) Bump the version
1. Edit `src/apps/ulti/package.json` and update the `"version"` field (for example: `0.2.0`).
2. Save the file; no other edits are required for a straight version bump.

## 2) Update release notes
Add a changelog entry so the automated GitHub Release body has real notes to publish:

1. Add a new section in `CHANGELOG.md` for the release (for example: `## [Desktop v0.2.1]`).
2. Summarise the key changes under that heading.

## 3) Commit and tag the bump
Run the commands below from the repository root, replacing the version string if needed:

```bash
git add src/apps/ulti/package.json CHANGELOG.md
git commit -m "Bump desktop version to v0.2.0"
git push origin HEAD

git tag v0.2.0
git push origin v0.2.0
```

## 4) Build installers locally (REL-001)
1. Install dependencies once per machine or whenever `package-lock.json` changes:

   ```bash
   cd src/apps/ulti
   npm ci
   ```

2. Generate the release artifacts. This command cleans old builds, compiles the TypeScript main and renderer bundles, and packages platform installers under `release/`:

   ```bash
   npm run release:prep
   ```

Expected outputs (versioned automatically):
- `release/OnePiece Studio Desktop Setup 0.2.0.exe`
- `release/OnePiece Studio Desktop-0.2.0.dmg`
- `release/OnePiece Studio Desktop-0.2.0.AppImage`

## 5) Publish the GitHub release
Pushing the `v*` tag triggers the `release-desktop` GitHub Actions workflow. It builds the installers on macOS, Windows, and Linux, then publishes a GitHub Release with the artifacts attached and the release notes pulled from `CHANGELOG.md`.

## 6) Share the download link
Send the GitHub Releases page URL to users: `https://github.com/<org>/<repo>/releases`.

Repeat the checklist for every desktop release to keep downloads predictable and verifiable.
