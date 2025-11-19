import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Ensure current folder is in sys.path so internal imports work
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())