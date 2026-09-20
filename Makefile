.PHONY: setup setup-backend setup-model dev dev-backend dev-frontend test train train-public verify

PYTHON ?= python3
BACKEND_PY := backend/.venv/bin/python
MODEL_PY := model_pipeline/.venv/bin/python

setup: setup-backend setup-model
	cd credit-passport-ui && npm ci

setup-backend:
	$(PYTHON) -m venv backend/.venv
	backend/.venv/bin/pip install -e 'backend[dev,model]'
	backend/.venv/bin/pip install -e model_pipeline

setup-model:
	$(PYTHON) -m venv model_pipeline/.venv
	model_pipeline/.venv/bin/pip install -e 'model_pipeline[test]'

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000

dev-frontend:
	cd credit-passport-ui && npm run dev -- --host 127.0.0.1 --port 5173

dev:
	./scripts/dev.sh

train:
	cd model_pipeline && .venv/bin/python scripts/train_icp_model.py

train-public:
	cd model_pipeline && .venv/bin/python scripts/download_data.py
	cd model_pipeline && .venv/bin/python scripts/train_models.py
	cd model_pipeline && .venv/bin/python scripts/train_secondary_benchmarks.py

test:
	cd backend && .venv/bin/pytest
	cd model_pipeline && .venv/bin/pytest
	cd credit-passport-ui && npm run lint
	cd credit-passport-ui && npm run typecheck

verify: test
	cd credit-passport-ui && npm run build
