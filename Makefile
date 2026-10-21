# noteveo — `make help` lista los objetivos; el detalle de la herramienta está en
# specs/001-imagen-fija/contracts/cli.md.

.DELETE_ON_ERROR:
MAKEFLAGS += --warn-undefined-variables --no-builtin-rules
.DEFAULT_GOAL := help

PY := .venv/bin/python

.PHONY: help install ci

##@ Preparación

install: ## Instala el paquete y las herramientas de desarrollo en .venv
	$(PY) -m pip install -q -e '.[dev]'

##@ Calidad

ci: ## ruff y pytest, lo mismo que hay que pasar antes de cada PR
	$(PY) -m ruff check noteveo tests
	$(PY) -m ruff format --check noteveo tests
	$(PY) -m pytest -q

# Generador de ayuda de prwhite (https://gist.github.com/prwhite/8168133), con las
# secciones `##@` de kubebuilder (kubernetes-sigs).
help: ## Muestra esta ayuda
	@awk 'BEGIN {FS = ":.*##"; printf "\nnoteveo — make \033[36m<objetivo>\033[0m\n"} \
	  /^[a-zA-Z_0-9%-]+:.*?##/ { printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
