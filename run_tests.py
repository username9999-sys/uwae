#!/usr/bin/env python3
"""Test runner script for the Universal Web Acquisition Engine."""

import subprocess
import sys
import os

def run_tests():
    """Run the test suite with proper PYTHONPATH."""
    # Set PYTHONPATH to include the src directory
    env = os.environ.copy()
    env['PYTHONPATH'] = os.path.join(os.path.dirname(__file__), 'src')
    
    # Run pytest
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/', '-v'],
        env=env,
        cwd=os.path.dirname(__file__)
    )
    
    return result.returncode

if __name__ == '__main__':
    sys.exit(run_tests())
