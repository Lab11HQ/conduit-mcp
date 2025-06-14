#!/bin/bash
npx pyright --project pyright-manual.json > pyright-output.txt 2>&1
echo "Type check complete. Results in pyright-output.txt"