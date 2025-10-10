# Workflow Tracing Pipeline

The `workflow_tracing` package distils structural scaffolding data into a macro-level
narrative of how a codebase works. A LangGraph-driven agent orchestrates four stages:

1. **Context seeding** – read the orchestration agent’s business summary (when
   available) and extract directory hints that should be explored first.
2. **Directory discovery** – fetch directory-level summaries from stored
   `DirectorySummaryRecord` rows, prioritising matches for the extracted hints.
3. **Profile deep dives** – surface representative `ProfileRecord` components for each
   highlighted directory so the agent can inspect real entry points and support code.
4. **Narrative synthesis** – group the gathered evidence into macro workflow phases
   (ingestion, retrieval, reasoning) and emit a clean, human-readable overview together
   with a structured JSON payload.

## Running the pipeline

```bash
python -m workflow_tracing.cli \
  --database-url postgresql+psycopg://archai:archai@localhost:55432/structural_scaffolding \
  --root-path /path/to/repo \
  --summary-path results/orchestration.json
```

Outputs are written by default to:

- `results/workflow_trace.md` – human-friendly narrative.
- `results/workflow_trace.json` – structured representation of the same narrative.

Use `--max-directories` and `--profiles-per-directory` to adjust the breadth and depth
of the trace. Add `--enable-llm-narrative` (optionally with `--narrative-model` and
`--narrative-system-prompt`) to let an LLM polish the macro narrative while still
falling back to the deterministic text when the call fails. The agent automatically
skips work that has already been completed during the current run.

## Interactive exploration inside Docker

For the top-down interactive explorer (`workflow_tracing.trace_top_down.cli`), make
sure the container session has a TTY attached; otherwise stdin is treated as a pipe
and the CLI disables interactive prompts. The `Makefile` provides a convenience target
that sets up the proper `docker compose exec -it …` invocation:

```bash
make trace-top-down TRACE_TOP_DOWN_FLAGS="--root-path /app/ragflow-main --summary-path results/orchestration.json"
```
_(The target reattaches stdin via `/dev/tty`, so run it from a real terminal, not from within another tool that strips the TTY.)_

You can also run it manually if you need finer control:

```bash
docker compose exec -it worker bash -lc 'cd /app && PYTHONPATH=/app python -m workflow_tracing.trace_top_down.cli --root-path /app/ragflow-main'
```

Both approaches ensure `stdin` remains a TTY so you can type follow-up component
keywords (for example, `document parser`) and receive iterative trace refinements.
