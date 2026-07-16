from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lifeos.bridge import BridgeApplication, StdioBridgeServer
from lifeos.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--actor-id", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    app = BridgeApplication(vault_root=config.vault_root, runtime_dir=config.runtime_dir, actor_id=args.actor_id)
    return StdioBridgeServer(app, reader=sys.stdin, writer=sys.stdout).serve()


if __name__ == "__main__":
    raise SystemExit(main())
