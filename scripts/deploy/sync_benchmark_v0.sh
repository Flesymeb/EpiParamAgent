#!/usr/bin/env bash
set -euo pipefail
source_dir=''; project=''; watch=0; interval=30; dry_run=0
state="${XDG_STATE_HOME:-$HOME/.local/state}/epi-param-agent/benchmark-v0-sync"
usage() { echo 'Usage: sync_benchmark_v0.sh --source DIR --project [HOST:]ABS_DIR [--once|--watch] [--interval 30] [--state-dir DIR] [--dry-run]'; }
while (($#)); do
 case "$1" in
 --source|--project|--interval|--state-dir)
  (($#>=2)) || { usage >&2; exit 2; }
  case "$1" in --source) source_dir=$2;; --project) project=$2;; --interval) interval=$2;; --state-dir) state=$2;; esac; shift 2;;
 --once) watch=0;shift;; --watch) watch=1;shift;; --dry-run) dry_run=1;shift;;
 --help|-h) usage;exit 0;; *) usage >&2;exit 2;; esac
done
[[ -n "$source_dir" && -n "$project" ]] || { usage >&2;exit 2; }
[[ "$interval" =~ ^[0-9]+$ ]] && ((interval>=1 && interval<=3600)) || exit 2
source_dir=$(realpath -e -- "$source_dir")
[[ -d "$source_dir" && -f "$source_dir/manifest.json" && "${source_dir##*/}" == benchmark_v0 ]] || { echo 'Source must be benchmark_v0 with manifest.json.' >&2;exit 2; }
[[ "$project" != *$'\n'* && "$project" != *$'\r'* ]] || exit 2
if [[ "$project" == *:* ]]; then
 host=${project%%:*}; remote_path=${project#*:}
 [[ "$host" =~ ^[A-Za-z0-9_][A-Za-z0-9_.@-]*$ && "$remote_path" == /* ]] || exit 2
 target="${host}:${remote_path%/}/dataset/benchmark_v0/"
else
 [[ "$project" == /* ]] || exit 2
 target="${project%/}/dataset/benchmark_v0/"; real_target=$(realpath -m -- "$target")
 [[ "$real_target" != "$source_dir" && "$real_target" != "$source_dir/"* && "$source_dir" != "$real_target/"* ]] || { echo 'Source and target must be separate trees.' >&2;exit 2; }
fi
state=$(realpath -m -- "$state")
[[ "$state" != "$source_dir" && "$state" != "$source_dir/"* ]] || { echo 'State must be outside dataset.' >&2;exit 2; }
if [[ -n "${real_target:-}" ]];then
 [[ "$state" != "$real_target" && "$state" != "$real_target/"* ]] || { echo 'State must be outside destination dataset.' >&2;exit 2; }
fi
for name in rsync flock sha256sum;do command -v "$name" >/dev/null;done
key=$(printf '%s\n%s' "$source_dir" "$target" | sha256sum);key=${key%% *}
mkdir -p -- "$state";exec 9>"$state/$key.lock"
flock -n 9 || { echo 'Sync already has an owner.' >&2;exit 75; }
log="$state/$key.log";args=(-a --checksum --no-owner --no-group --protect-args --mkpath --delay-updates --stats '--chmod=Du=rwx,Dgo=,Fu=rwX,Fgo=')
((dry_run)) && args+=(--dry-run)
trap 'if [[ -n ${sleep_pid:-} ]];then kill "$sleep_pid" 2>/dev/null || true;fi;exit 130' INT
trap 'if [[ -n ${sleep_pid:-} ]];then kill "$sleep_pid" 2>/dev/null || true;fi;exit 143' TERM
while :;do
 printf '%s sync_start dry_run=%s\n' "$(date -u +%FT%TZ)" "$dry_run" >>"$log"
 if rsync "${args[@]}" -e 'ssh -o BatchMode=yes' -- "$source_dir/" "$target" >>"$log" 2>&1;then
  printf '%s sync_complete\n' "$(date -u +%FT%TZ)" >>"$log";printf 'Sync complete; log: %s\n' "$log"
 else
  code=$?;printf '%s sync_failed exit=%s\n' "$(date -u +%FT%TZ)" "$code" >>"$log";printf 'Sync failed (exit %s); log: %s\n' "$code" "$log" >&2
  case "$code" in 10|12|24|30|35|255) ((watch)) || exit "$code";; *) exit "$code";; esac
 fi
 ((watch)) || break
 sleep "$interval" & sleep_pid=$!;wait "$sleep_pid";sleep_pid=
done
