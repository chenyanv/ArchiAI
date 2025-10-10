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
