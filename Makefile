# SmartUA Makefile —— 一条命令起全栈。
#
#   make setup      装后端依赖 + migrate + seed + 前端依赖
#   make dev        并行起后端 :8000 + 前端 :5173（vite proxy 已配）
#   make test       后端 pytest
#   make db-reset   清库 + migrate + seed
#
# 可用 PYTHON=python3.14 make setup 覆盖解释器（默认 python3）。

PYTHON ?= python3

.PHONY: setup dev test db-reset dev-backend dev-frontend

setup:
	$(PYTHON) -m pip install -r backend/requirements.txt
	cd backend && $(PYTHON) -m alembic upgrade head
	cd backend && $(PYTHON) init_campaign_data.py && $(PYTHON) init_alerts.py
	cd frontend && npm install

dev:
	@echo "启动后端 :8000 + 前端 :5173（Ctrl-C 后若 uvicorn 未退出，手动 pkill -f uvicorn）"
	cd backend && $(PYTHON) -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
	cd frontend && npm run dev

dev-backend:
	cd backend && $(PYTHON) -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && $(PYTHON) -m pytest -v

db-reset:
	rm -f backend/smartua.db
	cd backend && $(PYTHON) -m alembic upgrade head
	cd backend && $(PYTHON) init_campaign_data.py && $(PYTHON) init_alerts.py
