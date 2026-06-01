#!/bin/bash
# Usage: ./unsafe_backup.sh <target-dir>
TARGET=$1

# VULN: eval on user-controlled input -> command injection
eval "tar -czf backup.tgz $TARGET"

# BUG: unquoted variable + rm -rf -> word-splitting / catastrophic deletion if TARGET is empty
rm -rf $TARGET/*

echo "backed up $TARGET"
