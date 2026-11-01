#!/usr/bin/env python3
"""Run console commands on a LOCAL test server over RCON (what rcon-cli does). Standard library only.

    python3 -I DaveBridge/tools/rcon.py --port 25575 --password-file <file> "dave pending" "list"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_check import Rcon  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=25575)
    p.add_argument("--password-file", required=True)
    p.add_argument("commands", nargs="+")
    a = p.parse_args()
    rcon = Rcon(a.host, a.port, Path(a.password_file).read_text().strip())
    for cmd in a.commands:
        print("> %s\n%s" % (cmd, rcon.command(cmd).rstrip()))
