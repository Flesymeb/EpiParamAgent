"""MetaAgent-Epi CLI entry point.

Usage:
    python -m metaagent.cli [command] [options]
    python -m metaagent.cli screening run --input data.csv --output out.csv

For the full Click-based CLI with Rich styling, use:
    python -m metaagent.cli.__init__
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> None:
    """Run the full Click-based CLI."""
    from metaagent.cli import main as _cli_main
    _cli_main()


if __name__ == "__main__":
    main()
