import os
import sys

# Allow `import scorer`, `import config`, etc. from the stock_bot/ package
# root (the parent of this tests/ directory), since these modules aren't
# packaged with a setup.py/pyproject.toml.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
