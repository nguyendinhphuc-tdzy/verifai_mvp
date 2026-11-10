#!/usr/bin/env bash
# Push the current working tree (tracked + new, non-ignored files) to a
# Hugging Face Docker Space. Secrets are NOT pushed: set GEMINI_API_KEY and
# VERIFAI_ACCESS_CODE in the Space settings.
#
#   HF_TOKEN=hf_xxx HF_SPACE=username/verifai bash scripts/deploy_hf_space.sh
set -euo pipefail
: "${HF_TOKEN:?Set HF_TOKEN (write token from huggingface.co/settings/tokens)}"
: "${HF_SPACE:?Set HF_SPACE as username/space-name}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cd "$ROOT"
git ls-files -co --exclude-standard -z | while IFS= read -r -d '' f; do
  case "$f" in
    tests/*|docs/*|data/*|.github/*|*.sqlite3) continue ;;
  esac
  [ -f "$f" ] || continue
  mkdir -p "$STAGE/$(dirname "$f")"
  cp "$f" "$STAGE/$f"
done
cp deploy/hf_space_README.md "$STAGE/README.md"
if grep -rIl "GEMINI_API_KEY=[A-Za-z0-9_-]\{20,\}" "$STAGE" >/dev/null 2>&1; then
  echo "Refusing to deploy: a file looks like it contains an API key" >&2; exit 1
fi
cd "$STAGE"
git init -q -b main
git add -A
git -c user.name="VerifAI deploy" -c user.email="deploy@localhost" commit -qm "Deploy VerifAI demo"
git push -f "https://user:${HF_TOKEN}@huggingface.co/spaces/${HF_SPACE}" main
echo "Pushed. Build logs: https://huggingface.co/spaces/${HF_SPACE}"
