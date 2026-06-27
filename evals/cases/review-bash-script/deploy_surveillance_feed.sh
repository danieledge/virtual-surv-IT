#!/usr/bin/env bash
# Synthetic eval input - a deliberately flawed deployment helper for a
# surveillance feed loader. NOT production code. All values are synthetic.
# See expected.yaml for the planted ground truth.

# OK (forbidden / FP-trap): strict mode is correct hardening, NOT a bug.
# A reviewer must NOT flag this line as a defect.
set -euo pipefail

# SEC-1 (planted, critical): pipe a remote script straight into bash.
# Anyone who controls the URL (or the network path) gets code execution.
curl -fsSL https://feeds.example.invalid/install.sh | bash

# BUG-1 (planted, warning): unquoted variable - word-splitting and glob
# expansion. If FEED_FILES contains spaces or "*", this breaks or over-matches.
FEED_FILES=$(ls /var/feeds)
for f in $FEED_FILES; do
    process_feed $f
done

# SEC-2 (planted, critical): rm -rf on a path built from a variable that may be
# unset. With an empty DIR this becomes "rm -rf /" relative to cwd.
rm -rf "$DIR/"

echo "deploy complete"
