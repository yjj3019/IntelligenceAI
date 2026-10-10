# Dependency and source record

The optional web extra is locked in `uv.lock`; GUI packages are pinned in `web/package-lock.json`. They are installed locally from PyPI/npm without vendor CLI or browser installation. Runtime additions are FastAPI 0.143.0 (MIT), Uvicorn 0.54.0 (BSD-3-Clause), SQLAlchemy 2.1.4 (MIT), Psycopg 3.3.6 (LGPL-3.0; binary distributions include separately licensed libraries), Authlib 1.8.0 (BSD-3-Clause), HTTPX 0.28.1 (BSD-3-Clause), React/React DOM 19.3.0 (MIT), and Lucide React 0.468.0 (ISC). Web build/test tools include Vite 8.3.4, TypeScript 5.9.3 (Apache-2.0), Vitest 5.0.3 and ESLint 10.12.0. Consult each locked package's distribution metadata for transitive licenses; the original `dependency-licenses.json` describes the core and is not asserted to cover this new optional tree.

Official web integration references: [Authlib Starlette OAuth](https://docs.authlib.org/en/stable/oauth2/client/web/starlette.html), [SQLAlchemy row locking](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.Select.with_for_update), [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/), [Vite](https://vite.dev/guide/), and [React](https://react.dev/). Container recipes use official Node/Python/PostgreSQL/uv distributions; they are not runtime-verified or immutable-digest deployment attestations.

Application code is original IntelligenceAI code under MIT. No upstream source repository is copied or relicensed. Optional tools retain their own licenses. Installed dependency metadata is recorded in `dependency-licenses.json`; complete package versions, PyPI sources and artifact SHA256 hashes are fixed in `uv.lock`. Metadata records are evidence, not a legal determination. Unknown metadata must be reviewed before redistribution.

| Component | Fixed version | Official source / tag | License | Use |
|---|---|---|---|---|
| LangGraph runtime | 1.2.14 | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph), runtime source SHA `70dd64065bffaa3b6ab61a33f1f020fb54db8efa` | MIT | Installed |
| SQLite checkpointer | 3.1.0 | [PyPI](https://pypi.org/project/langgraph-checkpoint-sqlite/3.1.0/) | MIT | Installed |
| Pydantic | 2.12.3 | [PyPI](https://pypi.org/project/pydantic/2.12.3/) | MIT | Installed |
| MCP Python SDK | 1.26.0 | [official SDK tag](https://github.com/modelcontextprotocol/python-sdk/tree/v1.26.0), [PyPI](https://pypi.org/project/mcp/1.26.0/) | MIT | Local stdio server/client only; no network transport started |
| psutil | 7.2.2 | [PyPI](https://pypi.org/project/psutil/7.2.2/), [official API](https://psutil.readthedocs.io/) | BSD-3-Clause | Darwin only, fresh process birth identity and group enumeration |
| pytest | 8.4.2 | [PyPI](https://pypi.org/project/pytest/8.4.2/) | MIT | Development |
| Ruff | 0.14.0 | [PyPI](https://pypi.org/project/ruff/0.14.0/) | MIT | Development |
| Hatchling | 1.27.0 | [PyPI](https://pypi.org/project/hatchling/1.27.0/) | MIT | Locked development/build backend |
| Omnilane | v0.53.0 | [release](https://github.com/Seraphim0916/omnilane/releases/tag/v0.53.0), SHA `15d5c99b1de982651af1b5cb00d339319d965661` | MIT | Preparation/parser only; exact intended upstream and live enforcement unresolved |
| MCO | v0.12.1 | [release](https://github.com/mco-org/mco/releases/tag/v0.12.1), SHA `3cfce130362dbcc2aedda6170d1a31e39cf67d3e` | MIT | Preparation/parser only; live dispatch disabled |
| PAL | v9.8.2 | [release](https://github.com/BeehiveInnovations/pal-mcp-server/releases/tag/v9.8.2), SHA `fa78edca0b6bc04ab00ddf5694d855f1b946b87d` | Apache-2.0 | Preparation/parser only; live dispatch disabled |
| Gitleaks | v8.30.1 | [release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1), SHA `83d9cd684c87d95d656c1458ef04895a7f1cbd8e` | MIT | Mandatory optional scanner; unavailable native runtime remains UNVERIFIED |

Runtime and CLI versions are distinct; a LangGraph CLI release is not its Python runtime version. Research main-branch results are not treated as release contracts. Upstream version/SHA observations were independently researched in the parent task and pinned source references are recorded in [contracts](upstream-contracts.md).

LangSmith arrives as a transitive dependency of LangChain core; controller tracing is explicitly disabled. No cloud tracing account, endpoint or API key is configured or required. Updating the lock requires repeating adapter and security regressions. The repository does not download/install vendor CLIs or change accounts.

An optional development helper fetches the official Gitleaks release into ignored `.tools`, verifies its published SHA256 and extracts only the named binary. This is separate from live worker permissions. The verified Windows x64 archive SHA256 is `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`. The Windows binary was used to scan exact release blobs, while the native task scanner remains UNVERIFIED because Windows process tree enforcement is absent. CI retrieves official Linux and Darwin arm64/x64 assets for actual scanner regressions; Darwin release hashes are additionally pinned in the helper. The installer rejects linked destinations and replaces regular files with a fresh inode.



## Isolation test dependencies and retained source

The dedicated Ubuntu 22.04 CI job pins official Ubuntu bubblewrap
`0.6.1-1ubuntu0.3` and records its binary SHA and preinstalled compiler version.
[Package source](https://packages.ubuntu.com/jammy/bubblewrap). No local user-PC
backend package is installed. Static probe compilation uses the CI compiler only;
missing dependencies are BLOCKED, without installing a sandbox workaround.

The unchanged Omnilane Grok runner is retained solely for fake-vendor argv/retry
tests, from v0.53.0 commit `15d5c99b1de982651af1b5cb00d339319d965661`.
SHA256 `120910ce341e9bbfebb33f64c7d6ac72e7578fcfe20642016a649f035f0b613b`;
MIT license and attribution are adjacent to the file. This test asset does not
introduce a production transport or authentication capability.
