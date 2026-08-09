#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

CONFIG_FILE="${CONFIG_FILE:-scripts/project.config.yaml}"
DOCKER_IMAGE="${DOCKER_IMAGE:-ghcr.io/inti-cmnb/kicad9_auto_full:latest}"
KIBOT_ASSETS_CONFIG="${KIBOT_ASSETS_CONFIG:-scripts/kibot/kibot_assets.kibot.yaml}"
NAME="$(basename "${ROOT_DIR}")"
BOARD_BASE=""

cfg_get() {
  local key="$1"
  local file="$2"
  [[ -f "${file}" ]] || return 0
  awk -v k="${key}" '
    $0 ~ "^[[:space:]]*"k":[[:space:]]*" {
      v=$0
      sub("^[[:space:]]*"k":[[:space:]]*", "", v)
      sub(/[[:space:]]*#.*/, "", v)
      gsub(/^["'"'"']|["'"'"']$/, "", v)
      print v
      exit
    }
  ' "${file}"
}

# First pass: allow selecting an alternative config file.
for ((i=1; i<=$#; i++)); do
  if [[ "${!i}" == "--config" ]]; then
    j=$((i+1))
    CONFIG_FILE="${!j}"
    break
  fi
done

if [[ -f "${CONFIG_FILE}" ]]; then
  cfg_board="$(cfg_get board_name "${CONFIG_FILE}")"
  cfg_name="$(cfg_get output_name "${CONFIG_FILE}")"
  cfg_docker_image="$(cfg_get docker_image "${CONFIG_FILE}")"
  [[ -n "${cfg_board}" ]] && BOARD_BASE="${cfg_board}"
  [[ -n "${cfg_name}" ]] && NAME="${cfg_name}"
  [[ -n "${cfg_docker_image}" ]] && DOCKER_IMAGE="${cfg_docker_image}"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      shift 2
      ;;
    --name)
      NAME="${2:-}"
      shift 2
      ;;
    --board)
      BOARD_BASE="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${BOARD_BASE}" ]]; then
  PCB_FILE="$(ls *.kicad_pcb | head -n 1)"
  BOARD_BASE="${PCB_FILE%.kicad_pcb}"
fi

BOARD_FILE="${BOARD_BASE}.kicad_pcb"
SCHEMATIC_FILE="${BOARD_BASE}.kicad_sch"
if [[ ! -f "${SCHEMATIC_FILE}" ]]; then
  SCHEMATIC_FILE="$(ls *.kicad_sch | head -n 1)"
fi

echo "Board base: ${BOARD_BASE}"
echo "Asset name prefix: ${NAME}"
echo "Assets config: ${KIBOT_ASSETS_CONFIG}"

docker run --rm \
  -v "${ROOT_DIR}:/home/kicad/project" \
  -u "$(id -u):$(id -g)" \
  -w /home/kicad/project \
  --env "HOME=/tmp" \
  "${DOCKER_IMAGE}" \
  kibot -c "${KIBOT_ASSETS_CONFIG}" -b "${BOARD_FILE}" -e "${SCHEMATIC_FILE}"

cp "assets/${BOARD_BASE}-schematic.svg" "assets/${NAME}-schematic.svg"
cp "assets/${BOARD_BASE}-board_3d.png" "assets/${NAME}-board_3d.png"
