"""Allow ``python -m nightcrawler ...`` as an alias for the console script."""

import sys

from nightcrawler.cli import main

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
