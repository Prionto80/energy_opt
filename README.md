# GridWise LLM Energy Optimizer

[![Python Version](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/uv-managed-purple.svg)](https://github.com/astral-sh/uv)
[![Version](https://img.shields.io/badge/version-0.1.0-green.svg)](app/__init__.py)

GridWise is an intelligent energy management and load optimization system powered by Large Language Models (LLMs). It processes energy grid telemetry, interprets complex load demands, and provides validated, constraint-bounded optimization strategies through a web interface.

---

## Key Features

* **LLM Strategy Optimization:** Generates optimized energy dispatch and load schedules based on dynamic pricing and demand patterns.
* **Safety & Operational Guardrails:** Built-in guardrail layer ensures LLM suggestions remain strictly within safe operational bounds.
* **Strict Data Validation:** Utilizes strict schema validation for all grid input telemetry and API parameters.
* **Web Interface:** Interactive Web UI to monitor metrics, trigger optimization runs, and visualize recommendations.
* **Modern Development Tooling:** Built on Python 3.14 and managed with `uv` for ultra-fast, reproducible dependency management.

---

## Project Structure

```text
energy_opt/
├── app/
│   ├── __init__.py        # Package initialization (v0.1.0)
│   ├── guardrails.py      # Operational safety constraints for LLM outputs
│   ├── interpreter.py     # Data interpreter & prompt context builder
│   ├── optimizer.py        # Core energy optimization algorithms
│   ├── schemas.py          # Data models & typed definitions
│   └── validator.py        # Telemetry and input validation layer
├── templates/
│   └── index.html         # Web UI frontend dashboard
├── tests/
│   └── test_contract.py   # System integration and API contract tests
├── main.py                # Application entry point and web server
├── pyproject.toml         # Project dependencies & metadata
├── uv.lock                # Locked dependency manifest
└── README.md
```[cite: 1]

---

## Prerequisites & Installation

### Requirements

* **Python:** `^3.14`[cite: 1]
* **Package Manager:** [`uv`](https://github.com/astral-sh/uv) recommended[cite: 1]

### Installation Steps

1. **Clone the Repository**
   ```bash
   git clone [https://github.com/your-org/energy_opt.git](https://github.com/your-org/energy_opt.git)
   cd energy_opt
