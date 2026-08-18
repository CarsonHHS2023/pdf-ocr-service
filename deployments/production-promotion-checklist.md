# Production promotion checklist

- [ ] Required Backend CI passes on the latest promotion head.
- [ ] Production deploy workflow applies all seven validated overlays.
- [ ] Focused validators and pytest suite pass on the integrated workspace.
- [ ] Scope checks prove provider skip and OCRmyPDF dependencies are absent.
- [ ] Codex reviews the exact latest head with no unresolved actionable findings.
- [ ] All review threads are resolved.
- [ ] Promotion PR is manually merged to `main`.
- [ ] Production deployment workflow completes successfully.
- [ ] Production Space shows a new startup after the merge.
- [ ] `OpenCV-Test.pdf` completes in production.
- [ ] Pages 3, 8, 10, and 12 pass visual acceptance.
- [ ] Only after production acceptance, create the next issue branch from the test baseline.
