"""讓 `python -m twec` 等同 `twec` 指令。"""

import sys

from twec.cli import main

sys.exit(main())
