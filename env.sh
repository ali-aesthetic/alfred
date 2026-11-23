# Alfred's environment. Everything lives in ALFRED_HOME (default: ~/Library/Application Support/Alfred).
export ALFRED_HOME="${ALFRED_HOME:-$HOME/Library/Application Support/Alfred}"
export J="$ALFRED_HOME"
export UV_PYTHON_INSTALL_DIR="$J/python" UV_CACHE_DIR="$J/.uv-cache" UV_LINK_MODE=copy
export PIP_CACHE_DIR="$J/.pip-cache" HF_HOME="$J/models" TORCH_HOME="$J/models/torch"
export npm_config_cache="$J/.npm-cache" XDG_CACHE_HOME="$J/.cache"
export MPLCONFIGDIR="$J/.cache/mpl"
export PATH="$J/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export U2NET_HOME="$J/models/u2net"
