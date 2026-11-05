#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 2 || "${1:-}" == --help ]];then
 echo 'Usage: snapshot_benchmark_v0.sh /absolute/benchmark_v0 /absolute/new_run_dir'
 [[ ${1:-} == --help ]] && exit 0
 exit 2
fi
source_dir=$(realpath -e -- "$1");run_dir=$(realpath -m -- "$2")
[[ -d "$source_dir" && -f "$source_dir/manifest.json" && "${source_dir##*/}" == benchmark_v0 ]] || exit 2
[[ "$2" == /* && "$run_dir" != "$source_dir" && "$run_dir" != "$source_dir/"* ]] || { echo 'Run must be outside live dataset.' >&2;exit 2; }
[[ ! -e "$run_dir" && ! -L "$run_dir" ]] || { echo 'Existing run directory is never modified.' >&2;exit 2; }
mkdir -p -- "$(dirname -- "$run_dir")"
mkdir -- "$run_dir"
mkdir -- "$run_dir/inputs";exec 9>"$run_dir/inputs/.snapshot.lock"
flock -n 9 || { echo 'Snapshot already has an owner.' >&2;exit 75; }
[[ ! -e "$run_dir/inputs/benchmark_v0" && ! -e "$run_dir/inputs/benchmark_v0.SHA256.json" ]] || { echo 'Existing snapshot is never replaced.' >&2;exit 2; }
[[ -z $(find "$source_dir" -type l -print -quit) ]] || { echo 'Resolve dataset symlinks before freezing.' >&2;exit 2; }
temp_dir=$(mktemp -d "$run_dir/inputs/.benchmark_v0.XXXXXX")
trap 'chmod -R u+w -- "$temp_dir" 2>/dev/null || true;rm -rf -- "$temp_dir"' EXIT
python3 - "$source_dir" "$temp_dir" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
source,temp=map(Path,sys.argv[1:])
def hashes(root):
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
before=hashes(source)
subprocess.run(['rsync','-a','--no-owner','--no-group','--',str(source)+'/',str(temp/'benchmark_v0')+'/'],check=True)
if before!=hashes(source) or before!=hashes(temp/'benchmark_v0'):
 raise SystemExit('Dataset changed or copy differs; no snapshot published. Retry after sync settles.')
(temp/'benchmark_v0.SHA256.json').write_text(json.dumps(before,sort_keys=True,indent=2)+'\n')
PY
mv -- "$temp_dir/benchmark_v0" "$run_dir/inputs/benchmark_v0"
mv -- "$temp_dir/benchmark_v0.SHA256.json" "$run_dir/inputs/benchmark_v0.SHA256.json"
chmod -R a-w -- "$run_dir/inputs/benchmark_v0"
chmod a-w -- "$run_dir/inputs/benchmark_v0.SHA256.json"
printf 'Frozen dataset root: %s\n' "$run_dir/inputs/benchmark_v0"
