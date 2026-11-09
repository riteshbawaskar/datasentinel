#!/usr/bin/env python
"""Convenience entry point:  python run_tests.py --help   (see datasentinel/runner.py)"""
import sys

from datasentinel.runner import main

if __name__ == "__main__":
    sys.exit(main())
