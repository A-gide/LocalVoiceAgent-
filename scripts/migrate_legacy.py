#!/usr/bin/env python3
"""CLI utility to migrate legacy memory.db to Journal v2 (PR-017)."""
from __future__ import annotations

import sys
from lva.journal.migrate_legacy import main

if __name__ == "__main__":
    sys.exit(main())
