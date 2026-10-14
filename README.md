# Experiments

`letssee` is an `ament_cmake` ROS 2 Jazzy package for local model research.
Inference code in `letssee_llm/` also works without ROS, including in notebooks.
The existing `/llm/generate` service and `Generate.srv` remain available.

## Layout and dependencies

- `models/model_library.yaml`: central registry; each model has its own local folder.
- `prompts/*.yaml`: reusable task instructions and generation defaults.
- `schemas/*.schema.json`: independently reusable JSON Schemas.
- `srv/`: ROS request/response contracts.
- `letssee_llm/services/`: short Python callbacks, separate from inference.

ROS dependencies are declared in `package.xml`, including `sensor_msgs`, `rclpy`,
interface generation, and Python installation support. Use Python matching ROS
(Ubuntu 24.04 / Jazzy: Python 3.12). From this repository root:

```bash
source /opt/ros/jazzy/setup.bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For CPU-only installation, install PyTorch first using its CPU index:

```bash
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
```

For CUDA use a compatible PyTorch build from the
[official installation guide](https://pytorch.org/get-started/locally/).
Transformers 4.57+ supports the registered Qwen3-VL architecture. Its processor
also requires a Torchvision build matching PyTorch. Outlines 1.x
provides native PyTorch token constraints. Optional GGUF support needs
`python -m pip install 'llama-cpp-python>=0.3,<0.4'`; CPU/GPU compilation options
are described in the [llama-cpp-python documentation](https://llama-cpp-python.readthedocs.io/).
No external inference API, Ollama, or Accelerate is used.

## Model library and downloading

The registry includes:

```text
models/
├── model_library.yaml
├── general/
│   └── qwen3-0.6b/
├── coding/
│   └── qwen2.5-coder-1.5b-instruct/
└── vision/
    └── qwen3-vl-2b-instruct/
```

Each leaf directory contains all model artifacts, including tokenizer/configuration
files and Hugging Face download metadata. Existing weights were renamed into this
hierarchy without copying or downloading them. Registry IDs remain independent
of directory names, so prompts and service requests still use `general`, `coding`,
and `vision`.

| ID | Model | Backend | Capabilities |
| --- | --- | --- | --- |
| `general` | Qwen/Qwen3-0.6B | Transformers/PyTorch | Text, structured output, model internals |
| `coding` | Qwen/Qwen2.5-Coder-1.5B-Instruct | Transformers/PyTorch | Text, coding, structured output, model internals |
| `vision` | Qwen/Qwen3-VL-2B-Instruct | Transformers/PyTorch | Image/text, structured output, model internals |

Download from the repository root, using the activated environment:

```bash
PYTHONPATH=. python scripts/download_models --registry models/model_library.yaml
# Select only one model:
PYTHONPATH=. python scripts/download_models --registry models/model_library.yaml general
```

These native weights occupy several GB in total. Downloaded weights, auxiliary
files, and download metadata under model folders are ignored by Git and excluded
from ROS installation. The script skips complete models, resumes incomplete
Hugging Face snapshots, and reports each failed download with a nonzero exit
status. It checks the expected architecture, tokenizer vocabulary/config,
VLM image processor and chat template, and all indexed weight shards.
Model loading is the final compatibility check; file checks alone do not prove
that a model can run on the selected hardware.

Relative registry paths resolve against `models/` (the registry's directory), or
an explicit `--model-root`, regardless of the current working directory.
New entries declare `category` (`general`, `coding`, or `vision`), `format`
(`safetensors` or `gguf`), and a path of `category/model-directory`.
Directory names use lowercase letters, digits, dots, underscores, and hyphens.
Use distinct suffixes for revisions or quantizations, such as
`general/qwen3-0.6b-q4-k-m`, to avoid sharing files between variants.
Legacy entries without `category` retain absolute/path-to-file support.
`repo_id` is optional for manually supplied models;
`revision` can pin a Hugging Face commit (default: `main`). No downloads happen
inside the new service callbacks: registered models load from local files only,
once per model per node, on first use. `HF_HUB_OFFLINE=1` can also enforce offline
operation; `HF_HOME` controls Hugging Face caching.

To add another native model in the same category, create a new leaf directory
and a separate registry ID, retaining its source and capability metadata:

```yaml
  another_general_model:
    category: general
    format: safetensors
    backend: transformers
    path: general/another-model-v1
    repo_id: your-account/your-model
    revision: your-pinned-commit
    capabilities: [text, structured, pytorch]
```

Select the registry ID in a prompt template's `model` field or a service request's
`model_id`; services do not need model filesystem paths.

For GGUF text models, add an entry such as:

```yaml
  general_gguf:
    category: general
    format: gguf
    backend: llama_cpp
    path: general/my-model-q4-k-m
    filename: model-q4_k_m.gguf
    capabilities: [text, structured]
    options: {n_ctx: 4096, n_gpu_layers: 0, seed: 0}
```

Place the GGUF inside that directory, or supply `repo_id` and `revision` for
the downloader. `filename` selects the weight file within the directory. Optional
`auxiliary_files` lists additional filenames to download and verify alongside it,
including projection/configuration files when applicable. llama.cpp uses the
GGUF's chat template. Allowed load options are `n_ctx`, `n_gpu_layers`,
`n_threads`, and `seed`. GGUF models expose llama.cpp inference, not PyTorch
weights or activations. GGUF VLMs need architecture-specific vision projectors
and handlers; this implementation rejects them. Use the native `vision` model
for image analysis and direct model access.

## Build and start

Build with system Python and ROS dependencies, then activate the inference
environment when running nodes:

```bash
source /opt/ros/jazzy/setup.bash
cd /home/dorteel/ros2_ws
colcon build --packages-select letssee
source install/setup.bash
```

Run the new services in separate terminals, with ROS/workspace sourced and the
virtual environment activated. These examples use downloaded repository models:

```bash
python "$(ros2 pkg prefix letssee)/lib/letssee/generate_text_service" --ros-args \
  -p model_root:=/home/dorteel/ros2_ws/src/letssee/models -p device:=cpu

python "$(ros2 pkg prefix letssee)/lib/letssee/vlm_service" --ros-args \
  -p model_root:=/home/dorteel/ros2_ws/src/letssee/models -p device:=cpu
```

Use `device:=cuda` for native CUDA inference. The startup-only `data_dir`
parameter selects a directory containing `models/model_library.yaml`, `prompts/`,
and `schemas/`; it defaults to installed package assets. `model_root` defaults
to `~/.cache/letssee/models` when installed, or repository `models/` when imported
from source. To download into the installed default location, pass
`--model-root ~/.cache/letssee/models` to the downloader. `ros2 run letssee
<executable>` also works when dependencies are available to system Python.
Each node handles requests sequentially; separate nodes have separate model
instances and memory use.

## Launch one selected service

Build and source the workspace:

```bash
source /opt/ros/jazzy/setup.bash
cd /home/dorteel/ros2_ws
colcon build --packages-select letssee
source install/setup.bash
```

Select the local model root and activate the Python environment with the inference
dependencies. The launch file exposes `service` (`llm` or `vlm`) and `model`
(registry ID); defaults are `llm` and `general`:

```bash
export LETSSEE_MODEL_ROOT=/home/dorteel/ros2_ws/src/letssee/models
source /home/dorteel/ros2_ws/src/letssee/.venv/bin/activate
ros2 launch letssee llm.launch.py service:=llm model:=coding
```

Alternatively, start only the vision service:

```bash
ros2 launch letssee llm.launch.py service:=vlm model:=vision
```

The launch file uses the active `python3` for the selected executable. If using
the temporary validation environment, prepend `/tmp/letssee-model-env/bin` to
PATH instead of activating `.venv`. No model is loaded during launch: the chosen
model loads on its first request and remains cached. Unknown IDs or incompatible
capabilities fail before a service starts.

Minimal end-to-end `hi` example: keep the coding launch running, then in a second
terminal source ROS and `install/setup.bash` as above and call:

```bash
ros2 service call /llm/generate_text letssee/srv/GenerateText \
  "{prompt: hi, model_id: coding, schema_id: ''}"
```

Expect `success=True`, a nonempty `response`, and an empty `error_message`.
For structured output use `schema_id: structured_response`. For the vision launch:

```bash
ros2 service call /vlm/analyze_image letssee/srv/AnalyzeImage \
  "{image: {height: 1, width: 1, encoding: rgb8, step: 3, data: [255, 0, 0]}, prompt: hi, model_id: vision, schema_id: object_recognition}"
```

Press **Ctrl+C in the launch terminal** to stop the service. Only one selected
node is launched. Its read-only `model_id` parameter restricts requests: an empty
request ID uses the selected model, a matching ID is accepted, and a different
ID returns `success=False`. Selection also overrides a template's default model,
while preserving its instructions/generation settings. Unselected models remain
unloaded. Nodes started directly with an empty `model_id` retain multi-model
request selection. The legacy `/llm/generate` service is unchanged.

## Service calls and interfaces

```bash
ros2 service call /llm/generate_text letssee/srv/GenerateText \
  "{prompt: 'Explain attention briefly.', model_id: general, prompt_template: general, schema_id: ''}"

ros2 service call /llm/generate_text letssee/srv/GenerateText \
  "{prompt: 'Explain attention briefly.', model_id: general, prompt_template: general, schema_id: structured_response}"

# A 1x1 RGB image illustrates the contract; supply a real image for useful analysis.
ros2 service call /vlm/analyze_image letssee/srv/AnalyzeImage \
  "{image: {height: 1, width: 1, encoding: rgb8, step: 3, data: [255, 0, 0]}, prompt: 'Describe visible objects.', model_id: vision, prompt_template: object_recognition, schema_id: object_recognition}"
```

Both new interfaces return `success`, `response`, and `error_message`. Failures
return `success=false`, an empty response, and a clear error. Supported image
encodings are `rgb8`, `bgr8`, `rgba8`, `bgra8`, and `mono8`, including padded rows.
Other encodings and malformed dimensions/buffers are rejected.

For unpinned nodes, requests with a nonempty `model_id` override template model defaults. An empty
`prompt_template` means no template. **An empty ROS `schema_id` always means
unrestricted text**, including when a template names a schema; explicitly send
the schema ID to use it. In Python, omitting `schema_id` uses the template schema
default, while `schema_id=""` disables it. Generation defaults are greedy
(`temperature: 0.0`) with 128 new tokens; templates can change temperature and
`max_tokens`. Hardware/library differences can still affect reproducibility.

To add a ROS contract, place its `.srv` in the existing `srv/`, list it in
`rosidl_generate_interfaces()` in `CMakeLists.txt`, declare any referenced message
dependencies, rebuild, and import it from `letssee.srv`. Python implementations
belong under `letssee_llm/services/`, with executables installed to `lib/letssee`.

The legacy service retains its original behavior:

```bash
python "$(ros2 pkg prefix letssee)/lib/letssee/llm_service" --ros-args \
  -p model_name:=/home/dorteel/ros2_ws/src/letssee/models/general/qwen3-0.6b \
  -p device:=cpu -p max_new_tokens:=128
ros2 service call /llm/generate letssee/srv/Generate "{prompt: 'What is a robot?'}"
```

It loads one model at startup. A Hugging Face ID instead of a local path downloads
through the Hugging Face cache. Its minimal interface has no error field, so
inference errors are logged and return an empty response.

## Prompts and JSON Schemas

Add a YAML file in `prompts/`, following `general.yaml`: `model`, `system_prompt`,
optional `schema`, and `generation: {temperature: 0.0, max_tokens: 128}`. Select it
with `prompt_template` equal to the filename without `.yaml`. Other generation
parameters are rejected rather than ignored.

Add a schema as `schemas/<id>.schema.json` and select `<id>` in requests. Schema
definitions are validated before decoding. PyTorch/VLM generation uses an Outlines
logits processor to mask invalid next tokens; GGUF uses `LlamaGrammar.from_json_schema()`.
All structured outputs are parsed as complete JSON and validated with `jsonschema`
against the **original** schema before success is returned. Truncation, malformed
JSON, missing libraries, grammar compilation failures, or unsupported assertions
produce errors. Prompting alone never replaces decoding constraints.

The deliberately shared supported subset is: explicit single `type` (`object`,
`array`, `string`, `integer`, `number`, `boolean`, `null`); closed objects with
`properties`, `required`, `additionalProperties: false`; homogeneous arrays with
`items`, `minItems`, `maxItems`; and primitive `enum`. `$schema`, `title`, and
`description` are annotations. Numeric `minimum`/`maximum` require a finite enum
whose values already satisfy those bounds. Unbounded numeric ranges, `$ref`,
composition (`anyOf`/`oneOf`/`allOf`), type unions, `format`, `pattern`, string
length limits, additional properties, tuple arrays, and all other keywords are
rejected. Backend converters may further reject a supported schema/tokenizer
combination; no unconstrained fallback occurs.

The object-recognition schema rounds confidence estimates to tenths so its enum
can be enforced by both backends. These generated scores are **not calibrated
probabilities**. Bounds remain in the original schema for final validation.

Backend behavior is based on the
[Outlines backend API](https://dottxt-ai.github.io/outlines/latest/api_reference/)
and [llama-cpp-python grammar API](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/).

## Python and mechanistic interpretability

From the repository root, or after sourcing the installed workspace:

```python
from letssee_llm.inference import LocalModels

models = LocalModels('/home/dorteel/ros2_ws/src/letssee')
print(models.generate('Explain attention.', prompt_template='general',
                      schema_id='structured_response'))
llm = models.get('general')
model = llm.get_model()
tokenizer = llm.get_tokenizer()
inputs = tokenizer('A robot', return_tensors='pt').to(model.device)
outputs = model(**inputs, output_hidden_states=True, output_attentions=True)
```

The original unquantized PyTorch models expose weights, transformer layers, the
VLM vision encoder, forward hooks, and activations for future interventions.
Eager attention permits attention inspection. Only generation uses `no_grad()`;
direct calls can compute gradients. `LocalLLM` remains independently importable
from `letssee_llm.local_llm`. TransformerLens compatibility depends on its support
for the chosen architecture; no experiments or integration layer are added.

## Tests

The workspace-root `test.sh` is a symlink to the executable runner tracked in
this repository. It detects the package name and workspace from its own location,
so it also works when called from another directory.

```bash
cd /home/dorteel/ros2_ws
./test.sh                  # default: --unit
./test.sh --unit           # no model loading; real ROS calls with inference fixtures
./test.sh --integration    # model integration tests and real ROS service calls
./test.sh --all            # all automated tests and real ROS service calls
```

The runner sources the detected ROS distribution, incrementally builds the
package and its workspace dependencies, sources `install/setup.bash`, and runs
`colcon test` plus `colcon test-result`. It launches the text, vision, and legacy
services in a separate test domain, waits for readiness with a timeout, and makes
seven requests using `ros2 service call`: plain text, structured text, coding,
missing schema, structured image analysis, invalid image, and legacy generation.
It checks response fields and validates structured JSON against the original
schemas. It then stops those nodes and launches `llm/coding` and `vlm/vision`
sequentially using `ros2 launch`. These checks use the `hi` request twice, reject
requests for other models, trace that only the selected model initializes once,
and verify clean shutdown. Invalid IDs and incompatible capabilities must fail
promptly. Success ends with `PASS: ... single-model launch checks passed`.

Default/unit mode explicitly excludes model integration tests and uses the
production callbacks with deterministic inference fixtures. Full modes require
the existing local general, coding, and vision models and ML dependencies; they
fail rather than download files or silently skip missing prerequisites. All
modes force Hugging Face offline operation. Models are downloaded separately
using the commands above.

`TEST_PYTHON` selects the interpreter for automated tests and nodes; by default
the runner uses repository `.venv/bin/python`, then `python3` from PATH. Build
tools keep the ROS system interpreter for interface generation. For example:

```bash
TEST_PYTHON=/path/to/ros-compatible/venv/bin/python ./test.sh --all
TEST_BUILD_ROOT=/tmp/ros-model-tests ./test.sh --unit
TEST_READY_TIMEOUT=60 TEST_CALL_TIMEOUT=300 ./test.sh --integration
```

`ROS_DISTRO` selects a distribution if multiple versions exist under `/opt/ros`.
`LETSSEE_MODEL_ROOT` changes the local model root. `TEST_DOMAIN_ID` overrides the
random test domain (100–199); use a domain reserved for your tests when sharing
a machine. Build/install/log output defaults to the workspace root; setting
`TEST_BUILD_ROOT` redirects all output to a reusable directory. Per-run logs are
retained under `test-run.*`. Failure prints that path and log excerpts. EXIT,
INT, and TERM traps stop only process groups launched by the runner; it never
stops existing nodes or the ROS daemon.

When changing service behavior, update `test.sh`, its inference fixtures, and
response checks together so these commands continue to cover the current contracts.

For a direct Python check without the ROS workflow:

```bash
python3 -m pytest -q test
```

Unit tests mock downloads and inference. They cover registry/path handling,
auxiliary files and shards, caching/resume, templates, schemas, structured output
validation, unsupported features, GGUF grammar dispatch, ROS callbacks, and VLM
image processing. Offline integration tests use the downloaded `general` and
`vision` models with real PyTorch and Outlines. The text test forces JSON despite
a contrary prompt, and the VLM test exercises the object-recognition template.
They skip when local weights or ML dependencies are absent. Set
`LETSSEE_MODEL_ROOT` for a different model root. In isolated Python environments,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids unrelated system ROS pytest plugins.

Before distributing the package, choose a license in `package.xml`.
The unrelated Obsidian notes remain in `self-graph-origin/`.
