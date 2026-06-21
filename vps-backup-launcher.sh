#!/usr/bin/env python3
import sys
import os
import signal

sys.path.insert(0, '/app/share/vps-backup')
signal.signal(signal.SIGINT, signal.SIG_DFL)

from src.main import main
sys.exit(main())
