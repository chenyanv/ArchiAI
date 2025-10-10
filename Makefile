COMPOSE ?= docker compose
WORKDIR ?= /app
WAIT_INTERVAL ?= 5
SUMMARY_LIMIT ?=
SUMMARY_FLAGS ?=
AST_FLAGS ?=
DIRECTORY_FLAGS ?=
SYNTH_LIMIT ?=
SYNTH_FLAGS ?=
PROFILE ?=
PRINT_JSON ?= 0
DEBUG ?= 0
ORCHESTRATION_FLAGS ?=
TRACE_TOP_DOWN_FLAGS ?=
BOOL_TRUE := 1 true TRUE yes YES on ON

AST_ROOT ?= $(WORKDIR)/ragflow-main

RUN_WORKER_CMD = $(COMPOSE) exec -T worker bash -lc
RUN_WORKER_INTERACTIVE_CMD = $(COMPOSE) exec -it worker bash -lc
RUN_POSTGRES_CMD = $(COMPOSE) exec -T postgres bash -lc

.PHONY: all summaries wait-summaries directories synthesize verify up down status reset ast orchestration-agent trace-top-down

all: summaries wait-summaries directories synthesize verify
	@echo "🎉 Pipeline finished successfully!"

up:
	@echo "--> Starting core services (postgres, rabbitmq, worker)..."
	@$(COMPOSE) up -d postgres rabbitmq worker
	@echo "✅ Services are up."

down:
	@echo "--> Stopping all docker compose services..."
	@$(COMPOSE) down
	@echo "✅ Services stopped."

status:
	@$(COMPOSE) ps

reset:
	@echo "--> Resetting docker compose services and volumes..."
	@$(COMPOSE) down -v
	@echo "✅ Volumes removed. Bringing services back up..."
	@$(COMPOSE) up -d postgres rabbitmq worker
	@echo "✅ Fresh services ready."

ast:
	@echo "--> Building structural profiles via AST extraction..."
	@$(RUN_WORKER_CMD) 'set -euo pipefail; cd $(WORKDIR); PYTHONPATH=$(WORKDIR) python build_structural_scaffolding.py --root $(AST_ROOT) $(AST_FLAGS)'
	@echo "✅ Profiles stored."

summaries:
	@echo "--> Dispatching L1 summary tasks..."
	@$(RUN_WORKER_CMD) 'set -euo pipefail; cd $(WORKDIR); PYTHONPATH=$(WORKDIR) python -m structural_scaffolding.pipeline.dispatcher $(if $(SUMMARY_LIMIT),--limit $(SUMMARY_LIMIT),) $(SUMMARY_FLAGS)'
	@echo "✅ Summaries dispatched."

wait-summaries:
	@echo "--> Waiting for L1 summaries to finish..."
	@$(RUN_POSTGRES_CMD) 'set -euo pipefail; WAIT_INTERVAL="$(WAIT_INTERVAL)"; \
while true; do \
  remaining=$$(PGPASSWORD="$$POSTGRES_PASSWORD" psql -tA -v ON_ERROR_STOP=1 \
    -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" \
    -c "SELECT COUNT(*) FROM profiles WHERE kind IN ('"'"'file'"'"','"'"'class'"'"') AND summary_level IN ('"'"'NONE'"'"','"'"'LEVEL_1_IN_PROGRESS'"'"');"); \
  remaining=$${remaining//[[:space:]]/}; \
  if [ "$$remaining" = "0" ]; then \
    echo "✅ All profiles summarised."; \
    break; \
  fi; \
  echo "   $$remaining profiles still pending..."; \
  sleep "$$WAIT_INTERVAL"; \
	done'

directories:
	@echo "--> Generating directory-level summaries..."
	@$(RUN_WORKER_CMD) 'set -euo pipefail; cd $(WORKDIR); PYTHONPATH=$(WORKDIR) python scripts/run_directory_summaries.py $(DIRECTORY_FLAGS)'
	@echo "✅ Directory summaries complete."

synthesize:
	@echo "--> Synthesizing workflows..."
	@$(RUN_WORKER_CMD) 'set -euo pipefail; cd $(WORKDIR); PYTHONPATH=$(WORKDIR) python scripts/run_workflow_synthesis.py $(if $(PROFILE),--profile-id $(PROFILE),) $(if $(SYNTH_LIMIT),--limit $(SYNTH_LIMIT),) $(if $(filter $(PRINT_JSON),$(BOOL_TRUE)),--print-json,) $(if $(filter $(DEBUG),$(BOOL_TRUE)),--debug,) $(SYNTH_FLAGS)'
	@echo "✅ Workflow synthesis complete."

verify:
	@echo "--> Verifying pipeline results..."
	@$(RUN_POSTGRES_CMD) 'set -euo pipefail; \
PGPASSWORD="$$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" \
  -c "SELECT COUNT(*) AS profiles FROM profiles;" \
  -c "SELECT COUNT(*) AS entry_points FROM workflow_entry_points;" \
  -c "SELECT COUNT(*) AS workflows FROM workflows;"'
	@echo "✅ Verification complete."

orchestration-agent:
	@echo "--> Running orchestration agent..."
	@$(RUN_WORKER_CMD) 'set -euo pipefail; cd $(WORKDIR); PYTHONPATH=$(WORKDIR) python scripts/run_orchestration_agent.py $(ORCHESTRATION_FLAGS)'
	@echo "✅ Orchestration agent run complete."

trace-top-down:
	@echo "--> Launching top-down trace explorer (interactive)..."
	@$(RUN_WORKER_INTERACTIVE_CMD) 'set -euo pipefail; cd $(WORKDIR); PYTHONPATH=$(WORKDIR) python -m workflow_tracing.trace_top_down.cli $(TRACE_TOP_DOWN_FLAGS)' </dev/tty
	@echo "✅ Top-down trace explorer finished."
