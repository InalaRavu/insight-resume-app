"""Report the real page count of a .docx by asking Word to paginate it.

Layout limits in this project (the experience section must fit one page) can
only be verified by a real renderer -- python-docx has no concept of pages.
Developer utility, Windows + Word only; not imported by the application.

    python tools/page_count.py output.docx [more.docx ...]
"""
import sys
from pathlib import Path

import win32com.client

WD_STATISTIC_PAGES = 2
WD_DO_NOT_SAVE_CHANGES = 0


def page_count(path: Path) -> int:
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(str(path.resolve()), ReadOnly=True)
        try:
            doc.Repaginate()
            return int(doc.ComputeStatistics(WD_STATISTIC_PAGES))
        finally:
            doc.Close(WD_DO_NOT_SAVE_CHANGES)
    finally:
        word.Quit()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"{arg}: not found")
            continue
        print(f"{path.name}: {page_count(path)} page(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
