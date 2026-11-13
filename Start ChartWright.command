#!/bin/bash
# Same thing as the app, but in a visible Terminal window (handy if something goes wrong). Close the window to quit.
cd "$(dirname "$0")" && exec .venv/bin/python -m chartwright
