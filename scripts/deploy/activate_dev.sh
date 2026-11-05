#!/usr/bin/env bash
# Source this file; application dotenv loading handles .env.local.
if [[ "${BASH_SOURCE[0]}" == "$0" ]];then
 echo 'Use: source scripts/deploy/activate_dev.sh' >&2
 exit 2
fi
_epi_agent_root=$(cd -- "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/../.." && pwd -P) || return
if [[ ! -x "$_epi_agent_root/.venv/bin/python" ]];then
 echo 'Project .venv/bin/python is unavailable.' >&2
 unset _epi_agent_root
 return 1
fi
export VIRTUAL_ENV="$(realpath -e -- "$_epi_agent_root/.venv")"
export PATH="$_epi_agent_root/.venv/bin:/data/EpiParamAgent-runtime/bin:/data/EpiParamAgent-runtime/pi/node_modules/.bin:$PATH"
export UV_CACHE_DIR=/data/EpiParamAgent-runtime/uv-cache
export PYTHONPYCACHEPREFIX=/data/EpiParamAgent-runtime/pycache
cd -- "$_epi_agent_root" || return
unset _epi_agent_root
