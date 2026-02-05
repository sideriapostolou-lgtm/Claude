#!/bin/bash
# TikTok Shop UGC Generator - Quick Run Script

# Change to source directory
cd "$(dirname "$0")/src"

# Check if virtual environment exists
if [ -d "../venv" ]; then
    source ../venv/bin/activate
fi

# Run the CLI
python main.py "$@"
