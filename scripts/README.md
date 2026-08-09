# Scripts Workspace

This folder contains all automation related to:
- KiBot fabrication export
- STEP generation with mechanical holes from Gerber + Drill
- KiCad schematic field maintenance

## Structure

- `kibot/config.kibot.yaml`: Main KiBot config.
- `kibot/kibot_assets.kibot.yaml`: Assets KiBot config.
- `project.config.yaml`: Project-specific defaults (board name, output name, thickness, mechanical tools).
- `generate_step_mech.py`: Mechanical STEP generator.
- `add_lcsc_field.py`: Adds missing `LCSC` fields to placed schematic symbols.
- `fabrication.sh`: Fabrication pipeline (KiBot + mechanical STEP generator).
- `assets.sh`: Local assets pipeline (schematic + 3D render).
- `.venv/`: Local Python virtualenv used by script tooling.
- `.gitignore`: Ignore rules for script-local artifacts.

## Add missing LCSC fields

Preview the changes without modifying the schematic:

```bash
python3 scripts/add_lcsc_field.py --dry-run MacropadMK.kicad_sch
```

Apply them (close the schematic in KiCad first):

```bash
python3 scripts/add_lcsc_field.py MacropadMK.kicad_sch
```

Existing `LCSC` fields and their values remain unchanged. Power and helper symbols
such as `#PWR` and `#FLG` are skipped by default. Pass
`--include-power-symbols` if those symbols should receive the field too.

## Fabrication Script

Run:

```bash
./scripts/fabrication.sh
```

Behavior:
- Always runs inside Docker image `ghcr.io/inti-cmnb/kicad9_auto_full:latest`.

Default output name prefix comes from `output_name` in `scripts/project.config.yaml`.
If `output_name` is empty, repository folder name is used.
Override it with:

```bash
./scripts/fabrication.sh --name MyBoardName
```

Optional board base override:

```bash
./scripts/fabrication.sh --board ESP32_Shield_light
```

Optional mechanical tools override:

```bash
./scripts/fabrication.sh --mechanical-tools T5
```

## Assets Script (Local)

Run locally (uses Docker image `ghcr.io/inti-cmnb/kicad9_auto_full:latest`):

```bash
./scripts/assets.sh
```

Default asset prefix comes from `output_name` in `scripts/project.config.yaml`.
If `output_name` is empty, repository folder name is used.
Override it with:

```bash
./scripts/assets.sh --name MyBoardName
```

Optional board base override:

```bash
./scripts/assets.sh --board ESP32_Shield_light
```

## Project Config

Default config file: `scripts/project.config.yaml`

Example fields:

```yaml
board_name: ESP32_Shield_light
output_name: ESP32_Sheald_light
thickness: 1.6
mechanical_tools: T5
docker_image: ghcr.io/inti-cmnb/kicad9_auto_full:latest
```

Both scripts read this file automatically.
CLI options always override config values.

Use a different config file:

```bash
./scripts/fabrication.sh --config scripts/project.config.yaml
./scripts/assets.sh --config scripts/project.config.yaml
```

## What `fabrication.sh` Does

1. Runs KiBot with `scripts/kibot/config.kibot.yaml`.
2. Installs `cadquery` in the Docker runtime.
3. Runs `generate_step_mech.py` to create:
   - `Fabrication/STEP/<name>-STEP_Mechanical.step`

## Manual Script Usage

```bash
scripts/.venv/bin/python scripts/generate_step_mech.py \
  --edge-gerber Fabrication/Gerber/ESP32_Shield_light-Edge_Cuts.gbr \
  --drill Fabrication/Drill/ESP32_Shield_light-drill.drl \
  --out Fabrication/STEP/ESP32_Shield_light-STEP_Mechanical.step \
  --thickness 1.6
```

To force mechanical tools explicitly:

```bash
scripts/.venv/bin/python scripts/generate_step_mech.py \
  --edge-gerber Fabrication/Gerber/ESP32_Shield_light-Edge_Cuts.gbr \
  --drill Fabrication/Drill/ESP32_Shield_light-drill.drl \
  --out Fabrication/STEP/ESP32_Shield_light-STEP_Mechanical.step \
  --thickness 1.6 \
  --mechanical-tools T3,T4
```
