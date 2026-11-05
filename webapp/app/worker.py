"""Unbuffered managed subprocess entry point."""
import sys
from .jobs import run_job

if __name__ == '__main__':
    run_job(sys.argv[1], sys.argv[2])
