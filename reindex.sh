#!/usr/bin/env bash
# Linux host lifecycle; the Python builder uses a separate, persistent lock.
set -u
set -o pipefail
umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd) || exit 1
for prerequisite in docker flock python3 timeout; do
    command -v "$prerequisite" >/dev/null || { echo "reindex: missing $prerequisite" >&2; exit 1; }
done
[[ $(uname -s) == Linux && -d "$root/data" ]] || { echo 'reindex: Linux and existing data directory required' >&2; exit 1; }
exec 9>"$root/data/.reindex-operation.lock" || exit 1
flock -n 9 || { echo 'reindex: operation busy' >&2; exit 1; }
run_id=$(python3 -c 'import secrets; print(secrets.token_hex(16))') || exit 1
name="chago-reindex-$run_id"
pending=0
trap 'pending=130' INT
trap 'pending=143' TERM
compose=(docker compose --project-directory "$root" -f "$root/compose.yaml")
project=$("${compose[@]}" config --format json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])' 2>/dev/null) || {
    echo 'reindex: compose configuration unavailable' >&2; exit 1;
}
[[ -n "$project" ]] || exit 1
container_id=
terminal=0
status=1

manual() {
    echo "reindex: termination unconfirmed; manually verify name=$name run-id=$run_id project=$project before recovery" >&2
}

unconfirmed() {
    manual
    if (( pending != 0 )); then exit "$pending"; fi
    exit 1
}

# Resolve only our exact name, run label and Compose project. Returned ID alone
# is insufficient: a collision must never permit touching a foreign container.
resolve_own() {
    local record actual_id actual_name actual_run actual_project
    record=$(timeout 5 docker inspect --format '{{.Id}}|{{.Name}}|{{index .Config.Labels "chago.reindex-run"}}|{{index .Config.Labels "com.docker.compose.project"}}' "$name" 2>/dev/null) || return 1
    IFS='|' read -r actual_id actual_name actual_run actual_project <<< "$record"
    [[ -n "$actual_id" && "$actual_name" == "/$name" && "$actual_run" == "$run_id" && "$actual_project" == "$project" ]] || return 1
    [[ -z "$container_id" || "$container_id" == "$actual_id" ]] || return 1
    container_id=$actual_id
}

confirm_absent() {
    local matches
    matches=$(timeout 5 docker container ls -a --filter "name=^/${name}$" --format '{{.Names}}' 2>/dev/null) || return 1
    [[ -z "$matches" ]]
}

inspect_result() {
    local result state code
    result=$(timeout 5 docker inspect --format '{{.State.Status}}|{{.State.ExitCode}}' "$container_id" 2>/dev/null) || return 1
    IFS='|' read -r state code <<< "$result"
    [[ "$state" == exited || "$state" == dead ]] || return 1
    [[ "$code" =~ ^[0-9]+$ && "$code" -le 255 ]] || return 1
    terminal=1
    status=$code
}

terminate_own() {
    resolve_own || return 1
    if ! inspect_result; then
        timeout 15 docker stop --time 10 "$container_id" >/dev/null 2>&1 || true
        if ! inspect_result; then
            timeout 5 docker kill "$container_id" >/dev/null 2>&1 || true
            local deadline=$((SECONDS + 10))
            until inspect_result; do
                (( SECONDS < deadline )) || return 1
                sleep 1
            done
        fi
    fi
    return 0
}

recovery_command() {
    local remaining=$((recovery_deadline - SECONDS))
    (( remaining > 0 )) || return 1
    (( remaining <= 3 )) || remaining=3
    timeout "$remaining" "$@"
}

recover() {
    "${compose[@]}" up -d --no-deps app >/dev/null 2>&1 || return 1
    local recovery_deadline=$((SECONDS + 60)) id after before_state after_state
    local probe='import json,urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8000/health",timeout=2); assert r.status == 200 and json.load(r) == {"status":"ok"}'
    while (( SECONDS < recovery_deadline )); do
        (( pending == 0 )) || return 1
        id=$(recovery_command "${compose[@]}" ps -q app 2>/dev/null) || return 1
        if [[ -n "$id" && "$id" != *$'\n'* ]]; then
            before_state=$(recovery_command docker inspect --format '{{.State.Status}}|{{.RestartCount}}' "$id" 2>/dev/null) || return 1
            case "$before_state" in exited\|*|dead\|*|restarting\|*) return 1 ;; esac
            if [[ "$before_state" == running\|* ]]; then
                if recovery_command docker exec "$id" python -c "$probe" >/dev/null 2>&1; then
                    after_state=$(recovery_command docker inspect --format '{{.State.Status}}|{{.RestartCount}}' "$id" 2>/dev/null) || return 1
                    after=$(recovery_command "${compose[@]}" ps -q app 2>/dev/null) || return 1
                    if [[ "$id" == "$after" && "$before_state" == "$after_state" ]] && (( SECONDS < recovery_deadline )); then
                        echo 'reindex: app recovered (running and HTTP health verified)'
                        return 0
                    fi
                fi
            fi
        fi
        sleep 1
    done
    return 1
}

if (( pending != 0 )); then exit "$pending"; fi
if ! "${compose[@]}" stop app >/dev/null 2>&1; then
    echo 'reindex: app stop failed; build skipped' >&2
    recover || echo 'reindex: app recovery failed' >&2
    exit 1
fi
if (( pending != 0 )); then exit "$pending"; fi

# Traps only record signals while launch runs. Bash waits for this foreground
# command to finish before reconciliation, including when stdout ID is lost.
returned=$("${compose[@]}" run --detach --no-deps --name "$name" --label "chago.reindex-run=$run_id" app python -m app.indexer 2>/dev/null)
launch_status=$?
if [[ "$returned" =~ ^[a-f0-9]{12,64}$ ]]; then container_id=$returned; fi
if ! resolve_own; then
    if confirm_absent; then
        if (( pending != 0 )); then exit "$pending"; fi
        echo 'reindex: launch failed; no one-shot exists' >&2
        recover || echo 'reindex: app recovery failed' >&2
        exit 1
    fi
    unconfirmed
fi
if (( pending != 0 || launch_status != 0 )); then
    if ! terminate_own; then
        unconfirmed
    fi
else
    until inspect_result; do
        if (( pending != 0 )); then break; fi
        # Docker failure must not be mistaken for a live or completed builder.
        timeout 5 docker inspect "$container_id" >/dev/null 2>&1 || unconfirmed
        sleep 1
    done
    if (( pending != 0 )); then
        terminate_own || { manual; exit "$pending"; }
    fi
fi
(( terminal == 1 )) || unconfirmed
resolve_own || unconfirmed
timeout 5 docker rm "$container_id" >/dev/null 2>&1 || echo 'reindex: completed one-shot removal failed' >&2
if (( pending != 0 )); then
    echo 'reindex: interrupted; own one-shot terminated; recover with docker compose up -d app' >&2
    exit "$pending"
fi
if (( launch_status != 0 && status == 0 )); then status=1; fi
if ! recover; then
    echo 'reindex: app recovery failed' >&2
    if (( status == 0 )); then status=1; fi
fi
if (( pending != 0 )); then exit "$pending"; fi
exit "$status"
