"""One-time (or one-off update) interactive setup: saves your DNO region letter.

Run this locally: python -m scripts.setup_region
Writes to state/state_default.json, which is tracked in git -- commit and
push after running this so the region change reaches the scheduled job too.
"""

import json
from pathlib import Path

from core.octopus import VALID_REGIONS

STATE_PATH = Path(__file__).parent.parent / "state" / "state_default.json"


def main() -> None:
    print("Enter your DNO region letter. Options:")
    for letter, name in VALID_REGIONS.items():
        print(f"  {letter} - {name}")

    while True:
        region = input("Region letter: ").strip().upper()
        if region in VALID_REGIONS:
            break
        print(f"'{region}' isn't a recognised region letter, try again.")

    STATE_PATH.write_text(json.dumps({"region": region}, indent=2))
    print(f"Saved region '{region}' ({VALID_REGIONS[region]}) to {STATE_PATH}")
    print("Remember to commit and push state/state_default.json.")


if __name__ == "__main__":
    main()
