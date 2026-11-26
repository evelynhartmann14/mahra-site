#!/usr/bin/env bash
# Instala o editor de vídeo (idempotente). Uso: bash editor-video/install.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV=${VENV:-/opt/video}; MODELS=${MODELS:-/opt/video-models}; RS=${RS:-/opt/remotion-studio}

if [ ! -x "$VENV/bin/python" ]; then python3 -m venv "$VENV"; fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
"$VENV/bin/pip" install -q whisperx==3.8.6 demucs==4.1.0 scenedetect==0.7.3 mediapipe==1.2.3 \
  opencv-contrib-python-headless==5.1.0.95 transformers==4.57.6 huggingface_hub==0.36.2 accelerate==1.16.0 \
  soundfile librosa==1.0.1 einops==0.8.2 timm==1.0.31
SAM2_BUILD_CUDA=0 "$VENV/bin/pip" install -q sam2==1.1.0

mkdir -p "$MODELS/yunet"
[ -f "$MODELS/yunet/face_detection_yunet_2023mar.onnx" ] || curl -sSL -o "$MODELS/yunet/face_detection_yunet_2023mar.onnx" \
  https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
[ -d "$MODELS/ben2-src" ] || git clone -q --depth 1 https://github.com/PramaLLC/BEN2 "$MODELS/ben2-src"
"$VENV/bin/pip" install -q -r "$MODELS/ben2-src/requirements.txt"
mkdir -p "$MODELS/brands" && cp -r "$HERE/brands/." "$MODELS/brands/"

mkdir -p "$RS/src" "$RS/public"
cp "$HERE/remotion/package.json" "$HERE/remotion/tsconfig.json" "$HERE/remotion/remotion.config.ts" "$RS/"
cp "$HERE/remotion/src/"* "$RS/src/"
(cd "$RS" && npm install -s --no-audit --no-fund)

mkdir -p /opt/video-tools && cp "$HERE/mahra_edit.py" /opt/video-tools/ && chmod +x /opt/video-tools/mahra_edit.py
ln -sf /opt/video-tools/mahra_edit.py /usr/local/bin/mahra-edit
echo "editor de vídeo pronto: mahra-edit -h"
