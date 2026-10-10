# Public demo handoff

Build `web/` with `npm run build:public`, then run `uv run --frozen --extra web python scripts/pack_public_demo.py` at the repository root. The generated, ignored `public-demo.html` contains its own React/CSS assets with a hash-based CSP. It has no network connections, authenticated console, private database, login, model calls or public writes. KO/EN and hash routes work within a static embedding host.

Coordinate publishing this one artifact with the parent task's approved static hosting destination. Do not create a second Site or supply hosting credentials through this repository. Private deployment uses the separate [deployment guide](../docs/web-deployment.md).
