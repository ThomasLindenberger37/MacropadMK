#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

CONFIG_FILE="${CONFIG_FILE:-scripts/project.config.yaml}"
KIBOT_CONFIG="${KIBOT_CONFIG:-scripts/kibot/config.kibot.yaml}"
DOCKER_IMAGE="${DOCKER_IMAGE:-ghcr.io/inti-cmnb/kicad9_auto_full:latest}"
THICKNESS="${THICKNESS:-1.6}"
NAME="$(basename "${ROOT_DIR}")"
BOARD_BASE=""
MECH_TOOLS="${MECH_TOOLS:-}"

# First pass: allow selecting an alternative config file.
for ((i=1; i<=$#; i++)); do
  if [[ "${!i}" == "--config" ]]; then
    j=$((i+1))
    CONFIG_FILE="${!j}"
    break
  fi
done

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

if [[ -f "${CONFIG_FILE}" ]]; then
  cfg_board="$(cfg_get board_name "${CONFIG_FILE}")"
  cfg_name="$(cfg_get output_name "${CONFIG_FILE}")"
  cfg_thickness="$(cfg_get thickness "${CONFIG_FILE}")"
  cfg_mech_tools="$(cfg_get mechanical_tools "${CONFIG_FILE}")"
  cfg_docker_image="$(cfg_get docker_image "${CONFIG_FILE}")"

  [[ -n "${cfg_board}" ]] && BOARD_BASE="${cfg_board}"
  [[ -n "${cfg_name}" ]] && NAME="${cfg_name}"
  [[ -n "${cfg_thickness}" ]] && THICKNESS="${cfg_thickness}"
  [[ -n "${cfg_mech_tools}" ]] && MECH_TOOLS="${cfg_mech_tools}"
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
    --thickness)
      THICKNESS="${2:-}"
      shift 2
      ;;
    --mechanical-tools)
      MECH_TOOLS="${2:-}"
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
echo "Output name: ${NAME}"
echo "KiBot config: ${KIBOT_CONFIG}"
echo "Docker image: ${DOCKER_IMAGE}"
echo "Mechanical tools: ${MECH_TOOLS:-auto (NPTH)}"

docker run --rm \
  -v "${ROOT_DIR}:/home/kicad/project" \
  -u "$(id -u):$(id -g)" \
  -w /home/kicad/project \
  --env "HOME=/tmp" \
  --env "BOARD_BASE=${BOARD_BASE}" \
  --env "SCHEMATIC_FILE=${SCHEMATIC_FILE}" \
  --env "BOARD_FILE=${BOARD_FILE}" \
  --env "KIBOT_CONFIG=${KIBOT_CONFIG}" \
  --env "NAME=${NAME}" \
  --env "THICKNESS=${THICKNESS}" \
  --env "MECH_TOOLS=${MECH_TOOLS}" \
  "${DOCKER_IMAGE}" \
  sh -lc '
    kibot -c "${KIBOT_CONFIG}" -b "${BOARD_FILE}" -e "${SCHEMATIC_FILE}" &&
    python3 -m pip install --disable-pip-version-check -q --break-system-packages cadquery &&
    MECH_ARGS="" &&
    if [ -n "${MECH_TOOLS}" ]; then
      MECH_ARGS="--mechanical-tools ${MECH_TOOLS}";
    fi &&
    python3 scripts/generate_step_mech.py \
      --edge-gerber "Fabrication/Gerber/${BOARD_BASE}-Edge_Cuts.gbr" \
      --drill "Fabrication/Drill/${BOARD_BASE}-drill.drl" \
      --out "Fabrication/STEP/${NAME}-STEP_Mechanical.step" \
      --thickness "${THICKNESS}" \
      ${MECH_ARGS}
  '
