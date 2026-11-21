#!/usr/bin/env bash
set -euo pipefail
# Run as root on the Linux Docker host. Keep the model API off the public interface.
command -v ollama >/dev/null || { echo 'Install Ollama from https://ollama.com/download/linux first.' >&2; exit 1; }
install -d /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/sourcera.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=172.17.0.1:11434"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_KEEP_ALIVE=10m"
Environment="OLLAMA_NO_CLOUD=1"
MemoryMax=1400M
CPUQuota=150%
EOF
systemctl daemon-reload
systemctl enable --now ollama
systemctl restart ollama
for attempt in $(seq 1 20); do
  if curl -fsS http://172.17.0.1:11434/api/version >/dev/null; then break; fi
  sleep 1
done
OLLAMA_HOST=http://172.17.0.1:11434 ollama pull qwen3:0.6b
