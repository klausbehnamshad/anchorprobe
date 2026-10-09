# reports

Conformance reports written by `anchorprobe probe ... --out reports` and by the
live CI workflow. Generated files are ignored by git; the CI uploads them as
artifacts. Findings that are confirmed against a live service are copied into
`spec/STABLE-TEXT-ANCHOR.md`, section 9, with the service version.
