import ipaddress
import os

import uvicorn


def main():
    trusted = os.environ.get("IAI_TRUSTED_PROXY_IPS", "127.0.0.1").split(",")
    try:
        for address in trusted:
            ipaddress.ip_address(address.strip())
    except ValueError:
        raise SystemExit(
            "IAI_TRUSTED_PROXY_IPS requires explicit IP addresses, never wildcards"
        ) from None
    uvicorn.run(
        "intelligenceai.web.app:production_app",
        factory=True,
        host=os.environ.get("IAI_LISTEN_HOST", "127.0.0.1"),
        port=8080,
        proxy_headers=True,
        forwarded_allow_ips=",".join(address.strip() for address in trusted),
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
