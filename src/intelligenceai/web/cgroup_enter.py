"""Trusted host launcher waits for cgroup attachment before exec of fixed bwrap argv."""

import os
import sys


def main():
    descriptor = int(sys.argv[1])
    if os.read(descriptor, 1) != b"1":
        raise SystemExit(125)
    os.close(descriptor)
    os.execv(sys.argv[2], sys.argv[2:])


if __name__ == "__main__":
    main()
