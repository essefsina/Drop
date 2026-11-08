"""Make dropit_mt importable from the src/ layout."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
