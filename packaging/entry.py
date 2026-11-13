"""Entry point for the packaged app (double-click): start the server, open the browser, quit when the tab closes."""
import multiprocessing
import sys

from chartwright import paths


def _quiet_streams():
    # a windowed app has no console: send prints to a log file so nothing crashes
    if sys.stdout is None or sys.stderr is None:
        paths.RUN.mkdir(parents=True, exist_ok=True)
        log = open(paths.RUN / "chartwright.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _quiet_streams()
    from chartwright.cli import main
    sys.exit(main(sys.argv[1:] or ["serve", "--auto-quit"]))
