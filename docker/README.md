# Docker Setup

This directory contains **development/test Docker configuration** for running integration tests in containers.

## 🎯 Two Docker Setups

### 1️⃣ **Production Docker** (for end users)

**Location:** `../Dockerfile` (project root)  
**Purpose:** Run xls-analyser without installing Python/dependencies  
**Usage:** tbd

See [Main README](../README.md#docker-usage) for full usage guide.

---

### 2️⃣ **Dev/Test Docker** (this directory)

**Location:** `docker/docker-compose.yml` + `docker/app.Dockerfile`  
**Purpose:** Run tests in containers (used by CI and developers)  
**Usage:** `make docker-back && make docker-unit`

---

## 📦 Production Docker (End Users)

### Quick Start

```bash
# Build the image
docker build -t xls-analyser:latest .

# Use the wrapper script (recommended)
# TBD - Docker wrapper script to be implemented

# Or run directly (example)
docker run --rm -v $(pwd):/workspace xls-analyser:latest
```

### Features

- ✅ No Python installation required
- ✅ No dependency management needed
- ✅ Minimal image size (production deps only)
- ✅ Models cached in `~/.cache/hf`
- ✅ State persisted in `~/.local/share/xls-analyser`

### Volume Mounts

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|

| `~/.cache/hf` | `/home/appuser/.cache/hf` | model cache |

### Examples

tbd

```

---

## 🧪 Dev/Test Docker (Developers)

### Purpose

- Run integration tests in isolated containers
- Test Dockerfile builds in CI
- Consistent test environment across machines

### Files

```
docker/
├── docker-compose.yml   # Dev/test services (app only, no Ollama)
├── app.Dockerfile       # Dev/test image (includes test deps)
└── README.md            # This file
```

### Quick Start

```bash
# Build and start dev container
make docker-back

# Run unit tests inside container
make docker-unit

# Stop containers
docker compose -f docker/docker-compose.yml down
```

### Manual Usage

```bash
# Build dev image
docker compose -f docker/docker-compose.yml build

# Start container in background
docker compose -f docker/docker-compose.yml up -d

# Run tests inside container
docker compose -f docker/docker-compose.yml exec -T app \
    python -m pytest tests/unit -v

# View logs
docker compose -f docker/docker-compose.yml logs -f app

# Stop and remove containers
docker compose -f docker/docker-compose.yml down
```

### Differences from Production

| Feature | Production (`../Dockerfile`) | Dev/Test (`docker-compose.yml`) |
|---------|------------------------------|--------------------------------|
| **Dependencies** | Production only | Includes test deps |
| **Purpose** | End users | CI and developers |
| **Entrypoint** | Analysis script (TBD) | `backend.main` (keepalive) |
| **Volumes** | User XLS files | Backend/tests/logs (live reload) |
| **Size** | Minimal | Larger (test tools) |

---

## 🔧 Architecture Notes

### Why Two Dockerfiles?

1. **Production (`../Dockerfile`):**
   - Optimized for end users
   - Minimal dependencies (no pytest, no dev tools)
   - Clear entrypoint for analysis
   - Small image size

2. **Dev/Test (`app.Dockerfile`):**
   - Includes test dependencies
   - Mounts source code for live reload
   - Used by CI/CD pipelines
   - Runs `backend.main` keepalive


---

## 🚀 CI/CD Integration

The dev/test Docker setup is used in CI workflows:

```yaml
# .github/workflows/test.yml
- name: Run tests in Docker
  run: |
    docker compose -f docker/docker-compose.yml up -d
    docker compose -f docker/docker-compose.yml exec -T app \
        python -m pytest tests/unit tests/integration -v
```

---

## 📝 Development Workflow

### Local Development (no Docker)

```bash
# Preferred for fast iteration
# TBD - analysis script to be implemented
```

### Test with Production Docker

```bash
# Build production image
docker build -t xls-analyser:latest .

# Test as end user would
tbd
```

### Test with Dev Docker

```bash
# For integration tests that need isolation
make docker-back
make docker-unit
```

---

## 🆘 Troubleshooting

### Production Docker

**Image not found:**
```bash
docker build -t xls-analyser:latest .
```

**Permission errors:**
```bash
# Use user's UID/GID
docker run --rm -u $(id -u):$(id -g) -v $(pwd):/workspace xls-analyser:latest
```

**Model download fails:**
```bash
# Ensure HF cache directory is writable
mkdir -p ~/.cache/hf
chmod 755 ~/.cache/hf
```

### Dev/Test Docker

**Container won't start:**
```bash
# Check logs
docker compose -f docker/docker-compose.yml logs app

# Rebuild
docker compose -f docker/docker-compose.yml build --no-cache
```

**Tests fail in container but pass locally:**
```bash
# Ensure volumes are mounted correctly
docker compose -f docker/docker-compose.yml config | grep volumes -A 10
```

---

## 📚 Further Reading

- [Main README](../README.md) - Project overview and setup
- [Testing Approach](../docs/testing_approach.md) - Test strategy
- [Architecture Plan](../.cursor/plans/architecture_refactoring_plan.md) - Refactoring details

