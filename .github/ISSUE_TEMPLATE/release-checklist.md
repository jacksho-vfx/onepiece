---
name: "Release checklist"
about: "Step-by-step checklist for publishing a OnePiece Studio Desktop release"
labels: ["release"]
---

## Release checklist
- [ ] Bumped version in `src/apps/ulti/package.json`.
- [ ] Committed changes and pushed `main`.
- [ ] Created and pushed tag `vX.Y.Z` that matches `package.json`.
- [ ] Ran `npm run dist` (or `npm run release:prep`) and verified installers in `src/apps/ulti/release/`.
- [ ] Drafted GitHub release and uploaded binaries (.exe, .dmg, .AppImage).
- [ ] Updated release notes / changelog.
