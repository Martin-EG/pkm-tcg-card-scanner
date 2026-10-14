#!/usr/bin/env bash
# macOS dev machines only. The faiss-cpu and torch wheels each bundle their own
# libomp.dylib; loading both aborts with "OMP: Error #15". Point faiss at torch's
# copy so a single OpenMP runtime is loaded. Idempotent; re-run after reinstalling
# faiss-cpu. Not needed on Linux or Windows.
set -euo pipefail
cd "$(dirname "$0")/.."
SP=$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
FAISS_OMP="$SP/faiss/.dylibs/libomp.dylib"
if [[ -L "$FAISS_OMP" ]]; then
  echo "already linked: $FAISS_OMP -> $(readlink "$FAISS_OMP")"
  exit 0
fi
mv "$FAISS_OMP" "$FAISS_OMP.orig"
ln -s ../../torch/lib/libomp.dylib "$FAISS_OMP"
echo "linked $FAISS_OMP -> torch/lib/libomp.dylib"
