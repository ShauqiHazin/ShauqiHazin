# OrcaFlex Riser Installation Analysis — Automation Box

> **Automates static analysis for all riser installation stages using OrcaFlex Python API (OrcFxAPI)**

---

## 📁 Project Structure

```
orcaflex_riser_automation/
│
├── riser_installation_analysis.py   ← MAIN SCRIPT — run this
├── parametric_study.py              ← Parametric/sensitivity studies
├── requirements.txt
│
├── config/
│   └── installation_config.yaml    ← All project parameters here
│
├── utils/
│   ├── orcaflex_helpers.py         ← OrcaFlex API wrappers & code checks
│   ├── model_builder.py            ← Model construction from config
│   └── report_generator.py         ← Excel, text, and plot reports
│
├── templates/
│   ├── base_riser_model.dat        ← Base OrcaFlex model (generated)
│   └── base_riser_model_builder.py ← Script to build base model
│
├── output/                         ← Generated results (auto-created)
│   ├── *.xlsx                      ← Excel reports
│   ├── *.txt                       ← Text reports
│   ├── *.json                      ← JSON results
│   ├── *.sim                       ← OrcaFlex simulation files
│   └── plots/                      ← PNG plots
│
└── logs/                           ← Log files (auto-created)
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure OrcaFlex Path (if OrcaFlex is installed)

```python
# Add to your environment or at top of script:
import sys
sys.path.insert(0, r"C:\Program Files\Orcina\OrcaFlex\11.4\OrcFxAPI\Python")
```

### 3. Edit Configuration

Open `config/installation_config.yaml` and set your project parameters:
- Pipe dimensions (OD, WT, material grade)
- Water depth and environment
- Vessel parameters
- Installation stages
- Code check criteria

### 4. Run Analysis

```bash
# Run all enabled stages
python riser_installation_analysis.py

# Run with custom config
python riser_installation_analysis.py --config config/my_project.yaml

# Run single stage only
python riser_installation_analysis.py --stage 3

# Skip plot generation (faster)
python riser_installation_analysis.py --no-plots

# Force simulation mode (no OrcaFlex needed — for testing)
python riser_installation_analysis.py --sim
```

### 5. Run Parametric Study

```bash
# Vary water depth
python parametric_study.py --param water_depth --values 300 400 500 600 750

# Vary top tension
python parametric_study.py --param top_tension --values 200 250 300 350 400

# Vary current speed
python parametric_study.py --param current_speed --values 0.3 0.5 0.7 1.0
```

---

## ⚙️ What the Automation Does

### For Each Installation Stage:

| Step | Action |
|------|--------|
| 1 | Load YAML configuration |
| 2 | Build OrcaFlex model (vessel, line type, riser line, environment) |
| 3 | Configure model for stage (vessel position, riser length, layback) |
| 4 | **Run OrcaFlex static analysis** (`model.CalculateStatics()`) |
| 5 | Extract results along arc length (tension, moment, curvature, etc.) |
| 6 | Perform **DNV-ST-F101 code checks** |
| 7 | Calculate submerged weight breakdown |
| 8 | Save `.sim` file |
| 9 | Generate plots (structural results + riser profile) |

### Reports Generated:
- **Excel** (`.xlsx`) — per-stage sheets with results table + code checks
- **Text** (`.txt`) — plain-text summary
- **JSON** (`.json`) — machine-readable results
- **PNG plots** — structural results and riser profile per stage
- **Summary plot** — comparison across all stages

---

## 📐 Installation Stages (Default)

| Stage | Name | Vessel Pos (m) | Length (m) | Top Tension (kN) |
|-------|------|---------------|------------|-----------------|
| 1 | Initiation | 0 | 12 | 50 |
| 2 | Shallow Water Lay | 100 | 150 | 120 |
| 3 | Mid Water Lay | 300 | 350 | 200 |
| 4 | Deep Water Lay | 450 | 500 | 280 |
| 5 | Touchdown | 500 | 520 | 300 |
| 6 | Pull-in | 510 | 530 | 350 |

---

## 🔍 Code Checks (DNV-ST-F101)

| Check | Criterion |
|-------|-----------|
| Effective Tension | ≤ Max allowable tension |
| Compression | No compression (T ≥ 0) |
| Bend Radius | ≥ Min allowable bend radius |
| Von Mises Stress | ≤ SMYS × usage factor |
| Hoop Stress | Barlow's formula ≤ SMYS × usage factor |

---

## 🔧 Parametric Study Parameters

| Parameter | Description | Default Range |
|-----------|-------------|---------------|
| `water_depth` | Water depth (m) | 300–750 m |
| `top_tension` | Top tension (kN) | 200–400 kN |
| `current_speed` | Surface current (m/s) | 0.3–1.2 m/s |
| `seabed_stiffness` | Seabed stiffness (kN/m/m²) | 50–1000 |
| `stinger_angle` | Stinger angle (deg) | 30–50° |
| `wall_thickness` | Pipe wall thickness (m) | 0.019–0.032 m |

---

## 🛡️ Simulation Mode

If OrcaFlex is **not installed**, the tool runs in **Simulation Mode**:
- All OrcaFlex API calls are logged but not executed
- Plausible synthetic result data is generated for testing
- Reports and plots are still generated
- Use `--sim` flag to force simulation mode

---

## 📋 Configuration Reference

Key sections in `config/installation_config.yaml`:

```yaml
riser:
  outer_diameter: 0.3239    # m (12.75" OD)
  wall_thickness: 0.0254    # m (1.0" WT)
  SMYS: 450.0               # MPa (X65)

environment:
  water_depth: 500.0        # m

installation_stages:
  - stage_id: 1
    name: "Initiation"
    vessel_position: 0.0    # m
    riser_length_deployed: 12.0  # m
    top_tension: 50.0       # kN
    enabled: true

code_check:
  standard: "DNV-ST-F101"
  usage_factor: 0.9
  max_allowable_tension: 500.0  # kN
```

---

## 📞 OrcaFlex API Reference

Key OrcFxAPI calls used:

```python
import OrcFxAPI as ofx

model = ofx.Model()                          # New model
model = ofx.Model("path/to/model.dat")       # Load model
model.CalculateStatics()                     # Run static analysis
model.SaveData("output.dat")                 # Save model
model.SaveSimulation("output.sim")           # Save simulation

line = model["Production Riser"]             # Get line object
line.Length[0] = 500.0                       # Set length
result = line.StaticResult("Effective Tension", ofx.oeArcLength(100.0))
```

---

*Generated by OrcaFlex Riser Installation Automation Box*
