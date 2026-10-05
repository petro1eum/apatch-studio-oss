# Changelog

## 0.1.4 — Unreleased

- Studio opens without waiting for the full local history scan; Plans and Admin
  remain available while the read model is building or history is unavailable.
- The process-local read index reuses unchanged history objects and observes
  appended, replaced and removed objects without publishing a partial generation.
- Invalid history is shown explicitly, with bounded diagnostics and no fabricated
  contract coverage. Local documents and configuration remain accessible.
- Preserve existing signed Cowork import and result-delivery boundaries.
- Package, API health and OpenAPI metadata consistently report 0.1.4.

## 0.1.3

- Long or multiline change requests use a concise heading. The complete original
  request remains available under the “Original request” disclosure.
- Short change titles keep their existing wording. Both local Studio runs and
  imported changes use the same presentation.
- Change headings and request text use clearer sizing, normal body weight and
  wrapping on desktop and mobile layouts.
- Package, API health and OpenAPI version metadata consistently report 0.1.3.

## 0.1.2

See the [published release notes](https://github.com/petro1eum/apatch-studio-oss/releases/tag/v0.1.2).
