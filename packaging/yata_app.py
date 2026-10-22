"""PyInstaller で固めるときの入口（中身は yata.desktop）。"""

import sys

from yata.desktop import main

if __name__ == "__main__":
    main(sys.argv[1:])
