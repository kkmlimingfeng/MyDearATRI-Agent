# Qwen3-TTS GGUF backend

The backend uses `qwentts.cpp`, which loads both a Qwen3-TTS talker GGUF and
its audio codec GGUF. The existing `llama-cpp-python` text backend does not
implement Qwen3-TTS audio encoding, decoding, or voice cloning.

## Local setup

Run in WSL with the existing `atri` Conda environment. The runtime checkout,
generated audio, and runtime log stay under the Git-ignored `Qwen/` directory.
TTS model weights live in `models/TTS`; LLM GGUF weights live in `models/LLM`.
The URLs below use the local proxy on port 7897.

```bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate atri
python -m pip install cmake ninja
conda install -n atri -c nvidia cuda-nvcc=12.4.131 cuda-cudart=12.4.127 \
  cuda-cudart-dev=12.4.127 cuda-cudart-dev_linux-64=12.4.127 \
  cuda-cccl=12.4.127 libcublas-dev=12.4.5.8 -y
git -c http.proxy=http://127.0.0.1:7897 clone --recurse-submodules --depth 1 \
  https://github.com/ServeurpersoCom/qwentts.cpp.git Qwen/qwentts.cpp
PATH="$CONDA_PREFIX/bin:/usr/bin:/bin" LIBRARY_PATH="$CONDA_PREFIX/targets/x86_64-linux/lib" \
  cmake -S Qwen/qwentts.cpp -B Qwen/qwentts.cpp/build-cuda -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON \
  -DCMAKE_CUDA_COMPILER="$CONDA_PREFIX/bin/nvcc" -DCUDAToolkit_ROOT="$CONDA_PREFIX" \
  -DCMAKE_CUDA_ARCHITECTURES=86 \
  -DCMAKE_CUDA_FLAGS="-L$CONDA_PREFIX/targets/x86_64-linux/lib" \
  -DCUDA_cuda_driver_LIBRARY=/usr/lib/wsl/lib/libcuda.so \
  -DCMAKE_EXE_LINKER_FLAGS="-Wl,-rpath-link,$CONDA_PREFIX/lib" \
  -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-rpath-link,$CONDA_PREFIX/lib"
PATH="$CONDA_PREFIX/bin:/usr/bin:/bin" LIBRARY_PATH="$CONDA_PREFIX/targets/x86_64-linux/lib" \
  cmake --build Qwen/qwentts.cpp/build-cuda -j 4
mkdir -p models/TTS
curl -x http://127.0.0.1:7897 -L --fail -o models/TTS/qwen-talker-0.6b-base-Q8_0.gguf \
  https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF/resolve/main/qwen-talker-0.6b-base-Q8_0.gguf
curl -x http://127.0.0.1:7897 -L --fail -o models/TTS/qwen-tokenizer-12hz-Q8_0.gguf \
  https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF/resolve/main/qwen-tokenizer-12hz-Q8_0.gguf
curl -x http://127.0.0.1:7897 -L --fail -o models/TTS/qwen-talker-1.7b-base-Q4_K_M.gguf \
  https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF/resolve/main/qwen-talker-1.7b-base-Q4_K_M.gguf
curl -x http://127.0.0.1:7897 -L --fail -o models/TTS/qwen-tokenizer-12hz-Q4_K_M.gguf \
  https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF/resolve/main/qwen-tokenizer-12hz-Q4_K_M.gguf
```

Starting a workflow with a Qwen3-TTS node loads the selected native model on
CUDA0 ahead of the first response. The first synthesis starts the native service
on `127.0.0.1:8767` when it is not already running. Set `ATRI_TTS_URL` to a
different `127.0.0.1` port to avoid conflicts with other local services.
The default is `qwen3-0.6b-q8`; set `ATRI_TTS_MODEL=qwen3-1.7b-q4` to change
the startup selection. `ATRI_TTS_URL` can also point to a matching already running
`qwentts.cpp` service. `ATRI_TTS_BINARY`, `ATRI_TTS_TALKER`, and
`ATRI_TTS_CODEC` override the default paths.

Start only the Python backend and run a smoke test:

```bash
python web_server.py
python scripts/tts_smoke.py --port 8765 --text '你好，早上好。'
```

To exercise streamed local Qwen3 1.7B text with Qwen3 0.6B speech without the
frontend, run `python scripts/stream_tts_pair_smoke.py`. It writes a WAV under
`Qwen/` and reports when the first sentence is queued and when its first audio
chunk arrives.

## HTTP API

- `GET /api/tts/status`: selected model, native service readiness, and model file status.
- `GET /api/tts/models`: selectable model IDs and local file availability.
- `POST /api/tts/model`: JSON `{"model":"qwen3-0.6b-q8"}` or
  `{"model":"qwen3-1.7b-q4"}`. The current GPU model stops; the selected one
  loads on the next speech request. An active stream finishes before switching.
- `GET /api/tts/references`: WAV files in `data/ATRI语音包/` and the `atri` preset.
- `POST /api/tts/speech`: JSON body with `text`, optional `model` (switches to it),
  `reference` (default `atri`), `ref_text`, `language` (default `Chinese`), and `response_format`
  (`pcm` or `wav`). `pcm` streams signed 16-bit little-endian, 24 kHz mono;
  `wav` returns a complete file.

The `atri` preset joins `阿里嘎多.wav`, `请多指教.wav`, and `早上好.wav` with short
silences and leaves the source WAV files untouched. By default `ref_text` is
empty, which uses only the speaker embedding (x-vector). To use transcript
conditioning, pass `ありがとう。よろしくお願いします。おはようございます。`
explicitly. The single clips have matching Japanese transcripts in the code.
Other WAV files have no known transcript.

Place those three reference WAV files under `data/ATRI语音包/` locally. The voice
pack and GGUF weights are not part of the GitHub source commit.
