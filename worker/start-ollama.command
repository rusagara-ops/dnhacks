#!/bin/zsh
set -eu
cd "${0:A:h}"
export OLLAMA_MODELS="$PWD/.cache/ollama-models"
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=2
export OLLAMA_CONTEXT_LENGTH=8192
if [[ -x "$PWD/.cache/ollama/ollama" ]]; then
  exec "$PWD/.cache/ollama/ollama" serve
else
  exec ollama serve
fi
