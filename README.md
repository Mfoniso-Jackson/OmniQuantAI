# OmniQuantAI

Institutional autonomous quantitative trading foundation for the OmniQuantAI ecosystem.

This repository now has two layers:

- `src/omniquantai/`: clean paper-first trading platform foundation
- `weex/`, `core/`, `run.py`: WEEX AI Wars competition integration layer

Paper trading is the default. Live trading must remain fail-closed unless both safeguards are explicitly enabled:

```bash
ENABLE_LIVE_TRADING=true
CONFIRM_REAL_MONEY=true
```

## Current Milestone

Institutional Paper Trading MVP:

- Market data abstraction
- Paper broker
- Position manager
- Risk engine
- Strategy protocol and implementations
- Regime detector
- Performance analytics
- Logging
- Tests
- End-to-end run without exchange credentials

## Repository Layout

```text
src/omniquantai/
  domain/          Pure trading models and enums
  application/     Use cases and business services
  infrastructure/  Data adapters and logging setup
  interfaces/      CLI/API entry points
  adapters/        Future external broker/exchange adapters
  configuration/   Settings and safety gates

core/              Competition decision/router compatibility layer
weex/              WEEX client, execution, and position-state integration
ai_logging/        WEEX AI log payload builder/uploader
tests/             Unit and integration tests
```

## Run Paper Trading

```bash
PYTHONPATH=src python3 -m omniquantai.interfaces.cli
```

## Run Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## WEEX Competition Runner

The WEEX runner remains isolated from the paper engine:

```bash
python3 -m pip install -r requirements.txt
python3 run.py
```

By default, `python3 run.py` fails closed unless both live confirmations are set. Even after those confirmations, `config/competition.yaml` keeps `execution.dry_run: true` so decisions can be simulated without placing exchange orders.

Before any live order placement, review `config/competition.yaml`, API credentials, order size, leverage, `execution.dry_run`, and the live-trading safeguards.

## Engineering Principles

- Modular architecture
- Dependency injection
- Strict typing for the new platform layer
- Configuration-driven behavior
- Fail-safe defaults
- No duplicated trading business logic over time
- Every trade should be explainable
