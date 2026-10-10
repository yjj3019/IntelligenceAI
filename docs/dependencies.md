# Dependency and source record

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

