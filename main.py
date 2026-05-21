"""TUV Tools 启动入口"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from tuv_tools.app import main

if __name__ == "__main__":
    main()
