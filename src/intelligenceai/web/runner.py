"""A future isolated Linux runner must own containment and trusted evidence ingestion.

This release intentionally has no runnable dispatcher, provider credentials or shell.
Jobs remain HELD. Expired/uncertain leases never authorize a retry or forced cancellation.
"""


def main():
    raise SystemExit(
        "Linux runner is unimplemented; paid providers and external effects are disabled"
    )


if __name__ == "__main__":
    main()
