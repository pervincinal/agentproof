# Third-party plugin packages

These are **not redistributed** in this repository. Download them yourself so the
version you install is the one this study used.

## Ollama model provider (Dify plugin)

```bash
curl -L -o ollama-1.0.0.difypkg \
  https://marketplace.dify.ai/api/v1/plugins/langgenius/ollama/1.0.0/download
shasum -a 256 ollama-1.0.0.difypkg
# expected: 94c71230a068f2a5ef7281566e10486e532bc6f531de986fa0446b9f3103be35
```

Install it via the Dify UI (**Marketplace → Install plugin from → Local Package
File**), or via the plugin daemon API — see `target/app/IMPORT.md`.

> The Dify marketplace was unreachable from inside the containers during this
> study (`Reached maximum retries (3) for URL ...`), which is why the local-file
> path is documented at all. See `docs/OPS-FINDINGS.md`.
