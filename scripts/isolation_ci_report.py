"""Publish actual probe outcomes separately from a green contract-test job."""

import json
import os
import sys
from pathlib import Path
from xml.etree import ElementTree


def main():
    root = ElementTree.parse(sys.argv[1]).getroot()
    cases = list(root.iter("testcase"))
    blocked = [
        case.find("skipped").get("message", "")
        for case in cases
        if case.find("skipped") is not None
    ]
    failed = sum(
        case.find("failure") is not None or case.find("error") is not None for case in cases
    )
    status = (
        "FAILED"
        if failed
        else "BLOCKED"
        if blocked or len(cases) != 2
        else "VERIFIED_OFFLINE_PROBE"
    )
    evidence = [
        {
            "case": case.get("name"),
            "binding": {
                item.get("name"): item.get("value")
                for item in case.findall("./properties/property")
            },
        }
        for case in cases
    ]
    if status == "VERIFIED_OFFLINE_PROBE" and any(
        not row["binding"].get("manifest_digest") for row in evidence
    ):
        status = "BLOCKED"
        blocked.append("manifest-scoped evidence missing")
    report = {
        "status": status,
        "probe_cases": len(cases),
        "blocked": blocked,
        "failed": failed,
        "live_provider": "NOTRUN",
        "live_capability": "UNVERIFIED",
        "scope": "OFFLINE_OS_ISOLATION_ONLY",
        "evidence": evidence,
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=True)
    Path("isolation-result.json").write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write("\nOffline Linux isolation probe\n\n```json\n" + rendered + "\n```\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
