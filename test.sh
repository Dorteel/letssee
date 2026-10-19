#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./test.sh [--unit|--integration|--all]
  --unit         Unit tests and ROS CLI requests with mock inference (default).
  --integration  Offline model integration tests and real ROS CLI requests.
  --all          All automated tests and real ROS CLI requests.
Environment:
  ROS_DISTRO             Select an installed ROS distribution (auto if only one).
  TEST_PYTHON            Python for tests/nodes (default: repo .venv, then python3).
  TEST_BUILD_ROOT        Build/install/log directory (default: workspace root).
  LETSSEE_MODEL_ROOT     Local model directory (default: repository models/).
  TEST_READY_TIMEOUT     Service readiness timeout in seconds (default: 30).
  TEST_CALL_TIMEOUT      Request timeout in seconds (default: 180).
  TEST_DOMAIN_ID         ROS test domain (default: randomly selected 100..199).
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
mode=unit
case "${1:---unit}" in
  --unit) mode=unit ;;
  --integration) mode=integration ;;
  --all) mode=all ;;
  --help|-h) usage; exit 0 ;;
  *) usage >&2; fail "Unknown argument: $1" ;;
esac
(( $# <= 1 )) || fail "Supply only one test mode."

# Resolve the workspace-root symlink and run independently of the caller's cwd.
repo=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
workspace=$repo
while [[ ! -d "$workspace/src" || "$repo" != "$workspace/src/"* ]]; do
  [[ "$workspace" != / ]] || fail "Cannot find a workspace ancestor containing src/."
  workspace=$(dirname "$workspace")
done
cd "$workspace"
build_root=${TEST_BUILD_ROOT:-$workspace}
mkdir -p "$build_root"
build_root=$(cd "$build_root" && pwd)
python=${TEST_PYTHON:-}
if [[ -z "$python" ]]; then
  if [[ -x "$repo/.venv/bin/python" ]]; then python="$repo/.venv/bin/python";
  else python=$(command -v python3) || fail "python3 is required."; fi
fi
python=$(command -v "$python") || fail "Cannot find TEST_PYTHON."
PYTHONDONTWRITEBYTECODE=1 "$python" -m unittest discover -s "$repo/tests" -v
bash "$repo/world knowledge/psychoanalysis/test.sh"
ready_timeout=${TEST_READY_TIMEOUT:-30}
call_timeout=${TEST_CALL_TIMEOUT:-180}
for value in "$ready_timeout" "$call_timeout"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || fail "Timeouts must be positive integer seconds."
done

if [[ -z "${ROS_DISTRO:-}" ]]; then
  shopt -s nullglob
  setups=(/opt/ros/*/setup.bash)
  (( ${#setups[@]} == 1 )) || fail "Set ROS_DISTRO; expected one installed ROS distribution."
  export ROS_DISTRO=$(basename "$(dirname "${setups[0]}")")
fi
ros_setup="/opt/ros/$ROS_DISTRO/setup.bash"
[[ -f "$ros_setup" ]] || fail "ROS environment not found: $ros_setup"
# ROS setup scripts may reference unset variables; restore strict mode immediately.
set +u
source "$ros_setup"
set -u
for command in colcon ros2 timeout setsid; do
  command -v "$command" >/dev/null || fail "Required command is missing: $command"
done

package=$(python3 - "$repo/package.xml" <<'PY'
import sys
import xml.etree.ElementTree as ET
print(ET.parse(sys.argv[1]).getroot().findtext('name'))
PY
)
[[ -n "$package" && "$package" != None ]] || fail "Missing package name in package.xml."
mapfile -t packages < <(colcon --log-base "$build_root/log" list \
  --base-paths "$workspace/src" --names-only)
[[ " ${packages[*]} " == *" $package "* ]] || fail "Package $package was not discovered in $workspace/src."
printf 'Workspace: %s\nPackage: %s\nROS: %s\nMode: %s\nPython: %s\n' \
  "$workspace" "$package" "$ROS_DISTRO" "$mode" "$python"

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export LETSSEE_MODEL_ROOT=${LETSSEE_MODEL_ROOT:-$repo/models}
LETSSEE_MODEL_ROOT=$(readlink -m "$LETSSEE_MODEL_ROOT")
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-2} MKL_NUM_THREADS=${MKL_NUM_THREADS:-2}
export ROS_DOMAIN_ID=${TEST_DOMAIN_ID:-$((100 + RANDOM % 100))}
[[ "$ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] && (( ROS_DOMAIN_ID <= 232 )) || fail "Invalid TEST_DOMAIN_ID."
run_dir=$(mktemp -d "$build_root/test-run.XXXXXX")
export ROS_LOG_DIR="$run_dir/ros-log"
pids=()
is_running() {
  local active
  # Consult our own job table so a recycled PID cannot target an unrelated process.
  for active in $(jobs -pr); do [[ "$active" != "$1" ]] || return 0; done
  return 1
}
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  for pid in "${pids[@]}"; do
    if is_running "$pid"; then kill -TERM -- "-$pid" 2>/dev/null || true; fi
  done
  # Allow ros2 launch to propagate shutdown and finish its child-process escalation.
  for _ in {1..150}; do
    local running=0
    for pid in "${pids[@]}"; do is_running "$pid" && running=1; done
    (( running == 0 )) && break
    sleep 0.1
  done
  for pid in "${pids[@]}"; do
    if is_running "$pid"; then kill -KILL -- "-$pid" 2>/dev/null || true; fi
    wait "$pid" 2>/dev/null || true
  done
  if (( status != 0 )); then
    printf '\nFAILED; logs: %s\n' "$run_dir" >&2
    for log in "$run_dir"/*.log; do [[ ! -f "$log" ]] || tail -n 15 "$log" >&2; done
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"$python" - <<'PY' || fail "TEST_PYTHON needs pytest, PyYAML, jsonschema, Pillow, and ROS-compatible Python."
import pytest, yaml, jsonschema, PIL, rclpy
PY
if [[ "$mode" != unit ]]; then
  PYTHONPATH="$repo${PYTHONPATH:+:$PYTHONPATH}" "$python" - "$repo" <<'PY' || \
    fail "Integration prerequisites missing. Install requirements.txt and download models separately."
import os, sys
from pathlib import Path
import torch, torchvision, transformers, outlines
from letssee_llm.library import ModelLibrary, load_template
root = Path(sys.argv[1])
library = ModelLibrary(root / 'models/model_library.yaml', os.environ['LETSSEE_MODEL_ROOT'])
model_ids = {load_template(root / 'prompts', name)['model']
             for name in ('general', 'coding', 'object_recognition')}
for model_id in model_ids:
    library.verify(model_id)
PY
fi

# Verify model-directory layout even in lightweight mode, without reading weights.
legacy_model_path=$(PYTHONPATH="$repo${PYTHONPATH:+:$PYTHONPATH}" "$python" - "$repo" <<'PY'
import os, sys
from pathlib import Path
from letssee_llm.library import ModelLibrary, load_template
root = Path(sys.argv[1])
library = ModelLibrary(root / 'models/model_library.yaml', os.environ['LETSSEE_MODEL_ROOT'])
directories = set()
for model_id, entry in library.models.items():
    directory = library.path(model_id)
    assert directory.parent.name == entry['category'], f'Wrong category directory for {model_id}'
    assert directory not in directories, f'Shared model directory for {model_id}'
    directories.add(directory)
model_id = load_template(root / 'prompts', 'general')['model']
print(library.path(model_id))
PY
)

# Keep system Python for ROS interface generation; use the chosen Python for pytest.
colcon --log-base "$build_root/log" build --base-paths "$workspace/src" \
  --packages-up-to "$package" --build-base "$build_root/build" --install-base "$build_root/install" \
  --cmake-args -DBUILD_TESTING=ON "-DLLM_TEST_PYTHON=$python"
set +u
source "$build_root/install/setup.bash"
set -u
case "$mode" in
  unit) export PYTEST_ADDOPTS="--ignore=$repo/test/test_constrained_integration.py" ;;
  integration) export PYTEST_ADDOPTS="-k 'local_pytorch_constrained_generation or local_vlm_constrained_generation'" ;;
  all) export PYTEST_ADDOPTS= ;;
esac
colcon --log-base "$build_root/log" test --base-paths "$workspace/src" \
  --packages-select "$package" --build-base "$build_root/build" --install-base "$build_root/install" \
  --event-handlers console_direct+
colcon --log-base "$build_root/log" test-result --test-result-base "$build_root/build" --verbose

prefix=$(ros2 pkg prefix "$package")
start_service() {
  local role=$1 executable=$2
  if [[ "$mode" == unit ]]; then
    setsid "$python" "$repo/test/service_fixture.py" --service "$role" --ros-args \
      -p "data_dir:=$repo" -p "model_root:=$LETSSEE_MODEL_ROOT" >"$run_dir/$role.log" 2>&1 &
  else
    setsid "$python" "$prefix/lib/$package/$executable" --ros-args \
      -p "data_dir:=$repo" -p "model_root:=$LETSSEE_MODEL_ROOT" \
      -p "model_name:=$legacy_model_path" -p max_new_tokens:=32 \
      >"$run_dir/$role.log" 2>&1 &
  fi
  pids+=("$!")
}
start_service text generate_text_service
start_service vision vlm_service
start_service legacy llm_service

# Use graph discovery directly, without starting or stopping the ROS CLI daemon.
"$python" - "$ready_timeout" "${pids[@]}" <<'PY'
import os, sys, time
import rclpy
rclpy.init()
node = rclpy.create_node('test_service_readiness')
expected = {'/llm/generate_text', '/vlm/analyze_image', '/llm/generate'}
deadline = time.monotonic() + int(sys.argv[1])
try:
    while time.monotonic() < deadline:
        for pid in sys.argv[2:]:
            os.kill(int(pid), 0)
        found = {name for name, _ in node.get_service_names_and_types()}
        if expected <= found:
            print('All test services are available.', flush=True)
            break
        rclpy.spin_once(node, timeout_sec=0.1)
    else:
        raise RuntimeError(f'Service readiness timed out; missing: {sorted(expected - found)}')
finally:
    node.destroy_node()
    rclpy.try_shutdown()
PY

call_service() {
  local label=$1 service=$2 interface=$3 request=$4 expectation=$5
  printf 'Checking %s...\n' "$label"
  setsid timeout --foreground --signal=TERM --kill-after=5 "$call_timeout" \
    ros2 service call "$service" "$package/srv/$interface" "$request" \
    >"$run_dir/$label.log" 2>&1 &
  local request_pid=$! index=${#pids[@]}
  pids+=("$request_pid")
  wait "$request_pid" || fail "$label request failed or timed out."
  unset "pids[$index]"
  PYTHONPATH="$repo${PYTHONPATH:+:$PYTHONPATH}" "$python" \
    "$repo/test/check_service_response.py" "$run_dir/$label.log" "$expectation" "$repo/schemas"
}
call_service text /llm/generate_text GenerateText \
  "{prompt: 'Say hello briefly.', prompt_template: general, schema_id: ''}" text
call_service structured /llm/generate_text GenerateText \
  "{prompt: 'Say hello briefly.', prompt_template: general, schema_id: structured_response}" structured_response
call_service coding /llm/generate_text GenerateText \
  "{prompt: 'Give a Python expression adding a and b.', prompt_template: coding, schema_id: structured_response}" structured_response
call_service missing-schema /llm/generate_text GenerateText \
  "{prompt: hello, schema_id: missing}" error
call_service image /vlm/analyze_image AnalyzeImage \
  "{image: {height: 1, width: 1, encoding: rgb8, step: 3, data: [255, 0, 0]}, prompt: 'Identify visible objects.', prompt_template: object_recognition, schema_id: object_recognition}" object_recognition
call_service invalid-image /vlm/analyze_image AnalyzeImage \
  "{image: {height: 1, width: 1, encoding: 16UC1, step: 2, data: [0, 0]}, prompt: describe}" error
call_service legacy /llm/generate Generate "{prompt: 'hi'}" legacy

# Stop the baseline nodes before testing launch, so only one service is present.
stop_services() {
  local pid
  for pid in "${pids[@]}"; do
    if is_running "$pid"; then kill -INT -- "-$pid" 2>/dev/null || true; fi
  done
  for _ in {1..50}; do
    local running=0
    for pid in "${pids[@]}"; do is_running "$pid" && running=1; done
    (( running == 0 )) && break
    sleep 0.1
  done
  for pid in "${pids[@]}"; do
    is_running "$pid" && fail "Launched process $pid did not shut down cleanly."
    wait "$pid" || fail "Launched process $pid exited with an error."
  done
  pids=()
}
stop_services

check_launch() {
  local service=$1 model=$2 endpoint=$3 interface=$4 request=$5 expectation=$6
  local trace="$run_dir/launch-$service.loads"
  : > "$trace"
  local mock=0
  [[ "$mode" != unit ]] || mock=1
  PATH="$(dirname "$python"):$PATH" \
    PYTHONPATH="$repo/test/launch_fixture${PYTHONPATH:+:$PYTHONPATH}" \
    LETSSEE_LOAD_TRACE="$trace" LETSSEE_TEST_MOCK="$mock" \
    setsid ros2 launch "$package" llm.launch.py "service:=$service" "model:=$model" \
    >"$run_dir/launch-$service.log" 2>&1 &
  pids+=("$!")
  "$python" - "$endpoint" "$ready_timeout" "${pids[0]}" <<'PY'
import os, sys, time
import rclpy
rclpy.init()
node = rclpy.create_node('test_selected_launch')
endpoint, seconds, pid = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
deadline = time.monotonic() + seconds
all_services = {'/llm/generate_text', '/vlm/analyze_image', '/llm/generate'}
try:
    while time.monotonic() < deadline:
        os.kill(pid, 0)
        active = {name for name, _ in node.get_service_names_and_types()} & all_services
        if active == {endpoint}:
            break
        rclpy.spin_once(node, timeout_sec=0.1)
    else:
        raise RuntimeError(f'Expected exactly {endpoint}; found {active}')
finally:
    node.destroy_node()
    rclpy.try_shutdown()
PY
  [[ ! -s "$trace" ]] || fail "Launch eagerly initialized a model before any request."
  call_service "launch-$service-hi" "$endpoint" "$interface" "$request" "$expectation"
  call_service "launch-$service-repeat" "$endpoint" "$interface" "$request" "$expectation"
  call_service "launch-$service-restricted" "$endpoint" "$interface" \
    "${request/\{/{model_id: general, }" restricted
  "$python" - "$trace" "$model" <<'PY'
import json, sys
from pathlib import Path
loaded = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
assert loaded == [sys.argv[2]], f'Expected one initialization of the selected model, got {loaded}'
PY
  stop_services
}
check_launch llm coding /llm/generate_text GenerateText \
  "{prompt: hi, schema_id: structured_response}" structured_response
check_launch vlm vision /vlm/analyze_image AnalyzeImage \
  "{image: {height: 1, width: 1, encoding: rgb8, step: 3, data: [255, 0, 0]}, prompt: hi, schema_id: object_recognition}" object_recognition

for selection in 'llm missing' 'vlm coding'; do
  read -r service model <<< "$selection"
  status=0
  timeout --foreground --kill-after=5 "$ready_timeout" \
    ros2 launch "$package" llm.launch.py "service:=$service" "model:=$model" \
    >"$run_dir/invalid-$service.log" 2>&1 || status=$?
  (( status != 0 && status != 124 && status != 137 )) || fail "Invalid launch selection was not promptly rejected."
  "$python" - "$run_dir/invalid-$service.log" <<'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
assert 'Unknown model' in text or 'does not support vision' in text, text
PY
done
printf '\nPASS: %s tests, seven baseline requests, and single-model launch checks passed.\nLogs: %s\n' "$mode" "$run_dir"
