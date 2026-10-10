# Test-only upstream Grok runner

Source: Seraphim0916/omnilane v0.53.0, commit
`15d5c99b1de982651af1b5cb00d339319d965661`.
URL: https://github.com/Seraphim0916/omnilane/blob/15d5c99b1de982651af1b5cb00d339319d965661/scripts/runners/run-grok.sh
SHA256: `120910ce341e9bbfebb33f64c7d6ac72e7578fcfe20642016a649f035f0b613b`.
License: MIT, Copyright (c) 2026 Seraphim0916; see LICENSE.

These exact runner bytes are used only by a fake-vendor argv/retry harness.
The harness mocks common helpers, including policy decisions, and provides no
production authorization, caller context, credential or isolation evidence.
No production entry point selects this copy. It must never become a live runner.
