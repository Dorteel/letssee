#!/usr/bin/env python3
"""Repository entry point for the preservation-first research runner."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_runner import main
if __name__ == '__main__':
    main()
