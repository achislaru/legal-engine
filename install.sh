#!/usr/bin/env bash
# Install the legal engine on this computer (idempotent; never deletes or overwrites a real folder).
#   ./install.sh                     # links skills/* into ~/.claude/skills, Python environment, doctor
#   SKILLS_DIR=… ./install.sh        # another skills folder (e.g. a project's .claude/skills)
#   NO_DEPS=1 ./install.sh           # links only: no Python environment
#   WITH_PLAYWRIGHT=1 ./install.sh   # also the free browser engine for scheduled law monitoring
# The optional Firecrawl CLI (paid) is never installed here: the user installs it and signs in themselves.
set -euo pipefail
ENGINE="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.claude/skills}"
export SKILLS_DIR
mkdir -p "$SKILLS_DIR"

for src in "$ENGINE"/skills/*/; do
  [ -f "$src/SKILL.md" ] || continue
  name="$(basename "$src")"; dst="$SKILLS_DIR/$name"
  if [ -L "$dst" ]; then
    ln -sfn "${src%/}" "$dst"; echo "link   $name (updated)"
  elif [ -e "$dst" ]; then
    echo "SKIP   $name: $dst is a real folder — move it away yourself, then run again"
  else
    ln -s "${src%/}" "$dst"; echo "link   $name"
  fi
done

fail() { echo "FAIL   $1"; exit 1; }
if [ -z "${NO_DEPS:-}" ]; then
  if command -v uv >/dev/null 2>&1; then
    # why: each step checked by hand: `set -e` does not stop on a failed command on the left of `&&`
    if [ ! -x "$ENGINE/.venv/bin/python" ]; then
      uv venv -q --python 3.12 "$ENGINE/.venv" || fail "could not create .venv (uv venv)"
      echo "env    .venv (Python 3.12)"
    fi
    uv pip install -q --python "$ENGINE/.venv/bin/python" -r "$ENGINE/requirements.txt" \
      || fail "could not install the Python packages (requirements.txt)"
    echo "env    packages"
    if [ -n "${WITH_PLAYWRIGHT:-}" ]; then
      uv pip install -q --python "$ENGINE/.venv/bin/python" playwright || fail "could not install Playwright"
      "$ENGINE/.venv/bin/python" -m playwright install chromium || fail "could not download Chromium"
      echo "browser Playwright Chromium"
    fi
  else
    echo "MISS   uv — install it (https://docs.astral.sh/uv/), then run ./install.sh again"
  fi
fi

# NO_DEPS=1 is links only, so a missing .venv is expected there and doctor's verdict is only shown.
if python3 "$ENGINE/tools/doctor.py"; then
  echo "next   open Claude Code and say: «настрой юриста» / «configurează juristul» / «set up the lawyer»"
elif [ -z "${NO_DEPS:-}" ]; then
  exit 1
fi
# why: only a hint; the engine never runs npm and never signs in for the user.
echo "option Firecrawl (paid reading of official sites, you sign in yourself): npm i -g firecrawl-cli && firecrawl login --browser — or connect it at the wizard's first step"
