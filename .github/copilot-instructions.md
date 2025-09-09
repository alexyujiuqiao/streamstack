# StreamStack - Production-Grade LLM Serving Platform

**ALWAYS follow these instructions first and only fallback to additional search and context gathering if the information here is incomplete or found to be in error.**

StreamStack is a production-grade LLM serving platform built with FastAPI, featuring pluggable providers (OpenAI, vLLM), Redis-based queuing, rate limiting, and comprehensive observability.

## Current Repository State

**CRITICAL**: The main branch currently contains only `README.md` and `LICENSE` files. Do NOT attempt to build or run code that doesn't exist. The actual implementation is in development branches (see PR #1 for the intended architecture).

When code is eventually merged to main, follow the complete development procedures below.

## Environment Validation

### Currently Working Commands
These commands have been tested and work in the current environment:
```bash
# Check Python version (3.12+ available)
python3 --version

# Check Docker availability
docker --version

# Check Git functionality  
git --version
git remote -v

# Test virtual environment creation
python3 -m venv test_env
source test_env/bin/activate
deactivate
rm -rf test_env

# Test basic Python functionality
python3 -c "import json; print('Python basics working')"
```

### Commands That Will Fail Until Code Is Present
- `pip install -e ".[dev]"` - no pyproject.toml yet
- `uvicorn streamstack.main:app` - no streamstack package yet  
- `pytest` - no tests directory yet
- All application health checks - no running application
- Redis operations - Redis not installed in current environment

### System Dependencies
Install required system dependencies first:
```bash
# Update package manager (if needed)
apt-get update

# Install essential build tools (if not present)
apt-get install -y build-essential curl wget git

# Python 3.9+ is required - verify current version
python3 --version

# Install Redis for local development (when code is present)
apt-get install -y redis-server

# Docker is available for deployment
docker --version
```

**NOTE**: In the current environment, Python 3.12+ and Docker are already available. Redis installation may be needed when the actual application code is merged.

### Repository Setup
```bash
# Repository is already cloned in current environment
cd streamstack

# Create Python virtual environment (verified working)
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel
```

**NOTE**: These commands have been tested and work in the current environment.

### Development Dependencies Installation
**ONLY WHEN APPLICATION CODE IS PRESENT**
**TIMEOUT: Set timeout to 10+ minutes. NEVER CANCEL dependency installation.**
```bash
# Install development dependencies - takes 3-5 minutes
pip install -e ".[dev]" --timeout 600

# Install optional vLLM support if needed - takes 5-10 minutes
pip install -e ".[vllm]" --timeout 600
```

**NOTE**: These commands will fail in the current repository state since pyproject.toml doesn't exist yet. They will work once the application code is merged from development branches.

### Build Process
**TIMEOUT: Set timeout to 60+ minutes. NEVER CANCEL builds.**
```bash
# No traditional build step required for Python
# Dependencies are installed via pip above

# Verify installation
python -c "import streamstack; print(f'StreamStack {streamstack.__version__} installed')"
```

### Testing
**TIMEOUT: Set timeout to 30+ minutes. NEVER CANCEL test runs.**
```bash
# Run all tests - takes 5-15 minutes
pytest --timeout 1800

# Run tests with coverage - takes 10-20 minutes  
pytest --cov=streamstack --cov-report=term-missing --timeout 1800

# Run load tests (requires running server) - takes 10-30 minutes
locust -f tests/load/locustfile.py --host=http://localhost:8000 --users 10 --spawn-rate 2 --run-time 300s --timeout 1800
```

### Code Quality Checks
Run these before committing changes:
```bash
# Format code
black streamstack tests

# Sort imports
isort streamstack tests

# Lint code
flake8 streamstack tests

# Type checking
mypy streamstack
```

## Running the Application

### Local Development Server
```bash
# Ensure Redis is running
redis-server --daemonize yes

# Set required environment variables
export OPENAI_API_KEY="your_api_key_here"
export STREAMSTACK_PROVIDER="openai"

# Start development server
uvicorn streamstack.main:app --reload --host 0.0.0.0 --port 8000

# Alternative: Use the CLI command
streamstack
```

### Docker Compose Deployment
```bash
# Start all services (API, Redis, Prometheus, Grafana, vLLM)
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop services  
docker-compose down
```

### Health Checks
Verify the application is running properly (when code is present):
```bash
# Basic health check (will work when application is running)
curl http://localhost:8000/health

# Liveness probe
curl http://localhost:8000/health/live

# Readiness probe
curl http://localhost:8000/health/ready

# Metrics endpoint
curl http://localhost:8000/metrics
```

**NOTE**: These curl commands require the application to be running. In environments with limited internet connectivity, local HTTP requests will work but external API calls may fail.

## Validation Scenarios

**ALWAYS test these complete scenarios after making changes:**

### 1. Basic API Functionality
```bash
# Test chat completions endpoint
curl -X POST "http://localhost:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

### 2. Streaming Response Test
```bash
# Test streaming completions
curl -X POST "http://localhost:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{
    "model": "gpt-3.5-turbo", 
    "messages": [{"role": "user", "content": "Count to 5"}],
    "stream": true
  }'
```

### 3. Rate Limiting Validation
```bash
# Test rate limiting (should return 429 after limits exceeded)
for i in {1..150}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST "http://localhost:8000/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "test"}]}'
done
```

### 4. Observability Validation
```bash
# Check metrics collection
curl http://localhost:8000/metrics | grep streamstack

# Verify Grafana dashboards (if running Docker Compose)
curl http://localhost:3000/api/health

# Check Prometheus targets (if running Docker Compose)
curl http://localhost:9090/api/v1/targets
```

## Configuration

### Environment Variables
Set these environment variables for proper operation:

```bash
# LLM Provider Settings
export STREAMSTACK_PROVIDER="openai"  # openai, vllm, or custom
export OPENAI_API_KEY="your_api_key"
export OPENAI_BASE_URL="https://api.openai.com/v1"
export VLLM_BASE_URL="http://localhost:8001"

# Redis Configuration  
export REDIS_URL="redis://localhost:6379/0"

# Rate Limiting
export RATE_LIMIT_REQUESTS_PER_MINUTE=100
export RATE_LIMIT_TOKENS_PER_MINUTE=10000

# Queue Configuration
export MAX_QUEUE_SIZE=1000
export REQUEST_TIMEOUT=300

# Observability
export ENABLE_TRACING=true
export JAEGER_ENDPOINT="http://localhost:14268/api/traces"

# Debug mode for development
export STREAMSTACK_DEBUG=true
export STREAMSTACK_LOG_LEVEL="DEBUG"
```

## Key Directories and Files

### Repository Structure
```
streamstack/
├── streamstack/           # Main Python package
│   ├── core/             # Core application components
│   │   ├── app.py        # FastAPI application factory
│   │   ├── config.py     # Configuration management
│   │   ├── logging.py    # Structured logging setup
│   │   └── routes/       # API endpoint definitions
│   ├── providers/        # LLM provider implementations
│   ├── queue/           # Request queueing and rate limiting
│   └── observability/   # Metrics and tracing
├── tests/               # Test suites
├── docker-compose.yml   # Service orchestration
├── pyproject.toml      # Python project configuration
└── README.md           # Project documentation
```

### Important Files to Monitor
- `streamstack/core/config.py` - Configuration changes
- `streamstack/core/routes/chat.py` - API endpoint modifications
- `streamstack/observability/metrics.py` - Metrics definitions
- `pyproject.toml` - Dependency changes
- `docker-compose.yml` - Service configuration changes

## Timing Expectations

**Validated timings from current environment:**
- **Virtual Environment Creation**: ~3 seconds
- **Pip Package Upgrades**: ~4 seconds (with internet)
- **Repository Git Operations**: <1 second

**Expected timings when code is present:**
- **Dependency Installation**: 3-10 minutes (varies by network and package cache)
- **Test Suite**: 5-15 minutes (depends on test coverage and complexity)
- **Load Tests**: 10-30 minutes (configurable duration)
- **Docker Compose Startup**: 2-5 minutes (initial download may take longer)
- **API Response Time**: < 100ms for health checks, 1-30s for LLM requests

## Common Issues and Solutions

### Repository State Issues
```bash
# If commands fail because no code is present
git branch -r  # Check available branches
git log --oneline -10  # Check recent commits

# Look for development branches with actual code
git checkout <branch-with-code>  # If available
```

### Python Environment Issues
```bash
# If virtual environment issues occur
rm -rf venv  # Remove corrupted environment
python3 -m venv venv  # Recreate
source venv/bin/activate  # Reactivate
pip install --upgrade pip setuptools wheel  # Reinstall basics
```

### Redis Connection Errors (when code is present)
```bash
# Start Redis if not running
redis-server --daemonize yes

# Check Redis status
redis-cli ping  # Should return "PONG"

# If Redis not installed
apt-get update && apt-get install -y redis-server
```

### Missing Dependencies (when code is present)
```bash
# Reinstall dependencies
pip install -e ".[dev]" --force-reinstall --timeout 600

# Check for specific missing packages
pip list | grep fastapi
pip list | grep redis
```

### API Key Issues
```bash
# Verify API key is set and valid
echo $OPENAI_API_KEY

# Test API key validity (when internet available)
curl -H "Authorization: Bearer $OPENAI_API_KEY" https://api.openai.com/v1/models

# Set API key if missing
export OPENAI_API_KEY="your_api_key_here"
```

### Docker Issues
```bash
# Restart Docker services
docker-compose down && docker-compose up -d

# Check service logs
docker-compose logs -f api

# Verify Docker daemon is running
docker info
```

### Port Conflicts
```bash
# Check if port 8000 is in use
lsof -i :8000

# Kill process using the port
kill -9 $(lsof -t -i:8000)

# Use alternative port
uvicorn streamstack.main:app --port 8080
```

### Performance Issues (when application is running)
- Monitor metrics at `/metrics` endpoint
- Check queue depth and response times in metrics
- Verify Redis performance: `redis-cli info stats`
- Use load testing to identify bottlenecks: `locust -f tests/load/locustfile.py`
- Check system resources: `htop` or `top`

### Build/Installation Timeouts
- **NEVER CANCEL** long-running operations
- Use `--timeout 600` or higher for pip installs
- Check internet connectivity if downloads fail
- Clear pip cache if installation corrupted: `pip cache purge`

## CI/CD Integration

The repository includes GitHub Actions workflows (when implemented):
- Run `pytest` with full test suite
- Execute code quality checks (`black`, `isort`, `flake8`, `mypy`)
- Build and test Docker images
- Deploy to staging/production environments

**Always run the complete validation workflow locally before pushing changes.**

## Development Best Practices

1. **Check repository state first**:
   ```bash
   # See what branches are available
   git branch -r
   
   # Check for actual application code
   ls -la  # Current main has only README.md and LICENSE
   ```

2. **Always activate the virtual environment** before working:
   ```bash
   source venv/bin/activate
   ```

3. **Use proper branch workflow**:
   ```bash
   # Check available development branches
   git fetch --all
   git branch -r
   
   # If working with existing development code from PRs
   git checkout -b local-branch origin/development-branch-name
   
   # Create new feature branch from main
   git checkout main
   git pull origin main  
   git checkout -b feature/your-feature
   ```

4. **Test locally first** using the validation scenarios above

5. **Monitor application logs** for errors and performance issues:
   ```bash
   # Watch application logs
   tail -f logs/streamstack.log  # When logging is configured
   
   # Docker logs
   docker-compose logs -f api
   ```

6. **Use structured logging** with correlation IDs for debugging

7. **Implement proper error handling** with appropriate HTTP status codes

8. **Add metrics** for new features using the existing Prometheus setup:
   ```python
   from streamstack.observability.metrics import record_token_usage
   record_token_usage(provider="openai", model="gpt-3.5-turbo", prompt_tokens=100, completion_tokens=50)
   ```

9. **Update this documentation** when adding new features or changing workflows

10. **Follow the timeout guidelines**:
    - Set 60+ minute timeouts for builds  
    - Set 30+ minute timeouts for test suites
    - **NEVER CANCEL** long-running operations

Remember: This is a production system handling LLM requests. Always prioritize reliability, performance, and proper error handling in your changes.

## Final Validation Checklist

Before considering any implementation complete, verify ALL of the following:

### Environment Setup ✓ (Currently Working)
- [ ] Python 3.9+ available: `python3 --version`
- [ ] Virtual environment creation: `python3 -m venv test && rm -rf test`
- [ ] Git operations: `git status && git remote -v`
- [ ] Docker availability: `docker --version`

### Code Implementation (When Present)
- [ ] Dependencies install without errors: `pip install -e ".[dev]"` 
- [ ] Application starts: `uvicorn streamstack.main:app --host 0.0.0.0 --port 8000`
- [ ] Health checks respond: `curl http://localhost:8000/health`
- [ ] Metrics endpoint works: `curl http://localhost:8000/metrics`

### Full Integration Test (When Complete)
- [ ] Chat completions work: Send test request to `/v1/chat/completions`
- [ ] Streaming responses work: Test with `"stream": true`
- [ ] Rate limiting functions: Test exceeding request limits
- [ ] Redis operations succeed: Verify queue and rate limit storage
- [ ] Load testing passes: Run Locust tests for 5+ minutes
- [ ] Docker Compose deployment works: All services start and communicate

### Code Quality
- [ ] All tests pass: `pytest` 
- [ ] Code formatting: `black streamstack tests`
- [ ] Import sorting: `isort streamstack tests`
- [ ] Linting passes: `flake8 streamstack tests`
- [ ] Type checking: `mypy streamstack`

### Performance Validation
- [ ] Health check response time < 100ms
- [ ] Chat completion response time < 30s under normal load
- [ ] System handles concurrent requests without errors
- [ ] Memory usage remains stable under load
- [ ] No connection leaks or resource exhaustion

**Only mark the copilot instructions as complete when ALL items above are validated and working.**