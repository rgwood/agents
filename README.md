# Signal Agent

A Datadog monitoring agent built with the Claude Agent SDK. Analyzes logs and metrics to generate system health reports.

## Setup

1. Install dependencies:
   ```bash
   npm install -g @anthropic-ai/sandbox-runtime
   sudo apt install socat  # Linux only
   ```

2. Create `.env` with your API keys:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   DD_API_KEY=...
   DD_APPLICATION_KEY=...
   ```

## Usage

Run the sandboxed agent:
```bash
./run_signal.py "Report on the last 24 hours"
```

Or run directly without sandbox:
```bash
uv run signal_agent.py "Report on the last hour"
```

Reports are saved to `data/reports/`.

## Files

- `signal_agent.py` - Main agent using Claude Agent SDK + Datadog MCP
- `run_signal.py` - Wrapper that runs agent inside srt sandbox
- `.srt-settings.json` - Sandbox config (restricts filesystem writes to `data/`)
