# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Starplot is a Python library for creating star charts and maps of the sky. It provides four main plot types:
- **MapPlot**: General sky maps with various projections (Zenith, Orthographic, Stereographic, etc.)
- **HorizonPlot**: Shows the horizon at a specific time and place
- **OpticPlot**: Simulates views through telescopes and other optics
- **BasePlot**: Base class for all plot types

## Core Architecture

### Main Components
- **Plot Classes** (`src/starplot/`): MapPlot, HorizonPlot, OpticPlot inherit from BasePlot
- **Models** (`src/starplot/models/`): Star, Planet, Moon, Sun, DSO, Constellation objects
- **Plotters** (`src/starplot/plotters/`): Mixins for rendering stars, DSOs, constellations, Milky Way
- **Data Backend** (`src/starplot/data/`): DuckDB + Ibis for fast astronomical object queries
- **Styling** (`src/starplot/styles/`): Comprehensive styling system with themes and extensions
- **Projections** (`src/starplot/projections.py`): Cartopy-based map projections

### Key Dependencies
- **Matplotlib**: Primary plotting backend
- **Cartopy**: Map projections and coordinate systems
- **Skyfield**: Astronomical calculations and ephemeris
- **DuckDB + Ibis**: Fast data queries for stars/DSOs
- **Shapely**: Geometric operations

## Development Commands

### Docker-Based Development (Recommended)
```bash
# Build development container
make build

# Run tests
make test

# Run linting
make lint

# Format code
make format

# Type checking
make mypy

# Hash checks (visual regression tests)
make check-hashes

# Interactive shell
make shell

# Python shell
make shell
```

### Local Development
```bash
# Set Python path
export PYTHONPATH=./src/

# Run tests locally
python -m pytest tests/

# Run examples
cd examples && python examples.py
```

### Testing
- **Unit Tests**: Located in `tests/`, run with `make test`
- **Hash Checks**: Visual regression tests in `hash_checks/`, run with `make check-hashes`
- **Multi-Python Testing**: `make test-3.10`, `make test-3.11`, `make test-3.12`

## Working with Starplot Code

### Plot Creation Pattern
All plots follow this pattern:
1. Initialize plot class with parameters (projection, coordinates, time, styling)
2. Add celestial objects via plotter methods (`.stars()`, `.constellations()`, `.dsos()`)
3. Export or display (`.export()`, `.show()`)

### Data Queries
- Use `from ibis import _` for building query filters
- Stars: `where=[_.magnitude < 5.0]`
- DSOs: `where=[_.type == "galaxy"]`
- Constellations: `where=[_.iau_id.isin(["UMA", "ORI"])]`

### Styling System
- Base styles in `src/starplot/styles/`
- Extensions in `src/starplot/styles/ext/`
- Create custom styles by extending base `PlotStyle`

### Coordinate Systems
- **RA/DEC**: Right Ascension/Declination (celestial coordinates)
- **Alt/Az**: Altitude/Azimuth (horizon coordinates)
- Automatic coordinate transformations based on observer location/time

### File Structure Notes
- Main library code: `src/starplot/`
- Astronomical data: `src/starplot/data/library/`
- Examples: `examples/`
- Documentation: `docs/`
- Development tools: `hash_checks/`, `scripts/`

## Common Development Tasks

### Adding New Features
1. Create feature branch from `main`
2. Implement in appropriate module (`plotters/`, `models/`, etc.)
3. Add tests in `tests/`
4. Add hash checks if visual output changes
5. Update documentation in `docs/`

### Running Single Tests
```bash
# Run specific test file
make test ARGS="tests/test_map.py"

# Run specific test method
make test ARGS="tests/test_map.py::test_specific_method"
```

### Building Documentation
```bash
make docs-serve  # Local development server
make docs-build  # Build static site
```

### Data Updates
```bash
make db  # Rebuild entire database
make build-stars-mag11  # Update star catalog
make build-dsos  # Update DSO catalog
```