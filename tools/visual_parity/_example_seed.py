"""Execute visual comparison examples with the same label-placement RNG."""

import random
import runpy
import sys

COMPARISON_RANDOM_SEED = 42


def run_example(path: str) -> None:
    """Reset randomness immediately before running either comparison script."""
    random.seed(COMPARISON_RANDOM_SEED)
    runpy.run_path(path, run_name="__main__")


if __name__ == "__main__":
    run_example(sys.argv[1])
