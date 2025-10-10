# Workflow Tracing Pipeline

The `workflow_tracing` package builds on the structural scaffolding profiles to expose
end-to-end business workflows. A LangGraph-driven agent decides which stage to execute
next, ensuring the run remains adaptive and state-aware. The agent typically walks
through three phases:

1. **Entry point detection** – scans stored `ProfileRecord` rows for likely workflow
   triggers (web APIs, async consumers, scheduled jobs) using decorator, naming, and
   location heuristics.
2. **Call graph assembly** – converts each profile’s captured outbound calls into a
   lightweight call graph with best-effort resolution back to known profiles.
3. **Workflow synthesis** – walks the call graph from selected entry points, enriches
   each hop with the L1 summaries already persisted in the database, and produces a
   readable “script” describing the business flow.

## Running the pipeline

```bash
python -m workflow_tracing.cli \
  --database-url postgresql+psycopg://archai:archai@localhost:55432/structural_scaffolding \
  --root-path /path/to/repo \
  --summary-path results/orchestration.json
```

Outputs are written by default to:

- `results/entry_points.json`
- `results/call_graph.json`
- `results/workflow_scripts.json`

Use `--include-tests` to keep test modules in the entry scan, and `--max-depth` /
`--max-steps` to tune workflow expansion. The LangGraph agent will automatically skip
work that has already been completed during the current run.
