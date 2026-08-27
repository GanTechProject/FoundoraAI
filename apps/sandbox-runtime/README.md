# Foundora static website sandbox runtime

This image is the fixed `static-website@1` execution harness. It is not a service
and accepts no command-line options. At runtime it reads generated source from
`/site` and the strict route input from `/foundora-input/routes.json`, serves the
site on container loopback, and emits one bounded JSON result on stdout.

The eventual runner must supply the ADR-0026 engine controls. Running this image
directly is a Slice 0 development probe, not proof of the complete Phase 22
isolation or cleanup boundary.

`seccomp-profile.json` is vendored unchanged from the official Playwright 1.62.0
Docker support files. Its SHA-256 is pinned in `runtime-manifest.json`; it extends a
fail-closed Docker syscall allowlist with the user-namespace operations required to
keep Chromium's own sandbox enabled for untrusted pages.
