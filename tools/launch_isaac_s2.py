#!/usr/bin/env python3
"""Declared isaac_vr_record profile, sharing exact S1 pins and explicit rollback."""
import sys
from launch_isaac_s1 import main

if __name__ == '__main__':
    raise SystemExit(main(['--teleop', *sys.argv[1:]]))
