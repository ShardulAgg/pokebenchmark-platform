# pokebenchmark

The benchmarking orchestrator — spawn LLM agent runs (or manual human runs) against Pokemon GBA ROMs, catalog save states, track per-run results, and serve a REST/WebSocket API to the [dashboard](https://github.com/ShardulAgg/pokebenchmark-dashboard).

## Architecture

```
         ┌────────────────────┐
         │  Dashboard (React) │
         └──────────┬─────────┘
                    │ /api/*, /ws/*
         ┌──────────▼─────────┐
         │ Orchestrator (API) │
         │  catalog (SQLite)  │
         └──┬──────────────┬──┘
            │              │
    Docker API         in-process
            │              │
    ┌───────▼──────┐  ┌────▼──────┐
    │ Agent run    │  │ Manual    │
    │ containers   │  │ sessions  │
    └──────────────┘  └───────────┘
```

- **Agent runs** are spawned in Docker containers running the [pokebenchmark-agent](https://github.com/ShardulAgg/pokebenchmark-agent) session runner.
- **Manual runs** host an emulator session inside the orchestrator process; the dashboard drives it via `/api/runs/{id}/press`, `/wait`, `/save-state`, etc.

## Components in this repo

- `pokebenchmark_platform.orchestrator` — FastAPI app with routes for runs, save states, games, skills, manual control, and WebSocket live streams
- `pokebenchmark_platform.catalog` — SQLite catalog models and async DB for runs + save states
- `pokebenchmark_platform.recording` — ffmpeg video recorder
- `Dockerfile` / `docker-compose.yml` — build recipe with mGBA Python bindings

## Run

```bash
docker compose up --build
```

Orchestrator on `:8000`, dashboard proxies through on `:3000`.

## Related repos

- [pokebenchmark-emulator](https://github.com/ShardulAgg/pokebenchmark-emulator) — GBA wrapper + game adapters
- [pokebenchmark-agent](https://github.com/ShardulAgg/pokebenchmark-agent) — LLM agent runtime
- [pokebenchmark-dashboard](https://github.com/ShardulAgg/pokebenchmark-dashboard) — React UI

## License

MIT
