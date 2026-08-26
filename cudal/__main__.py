"""Enables `python -m cudal` (same as `python -m cudal.cli`)."""
from cudal.cli import main

if __name__ == "__main__":
    main()