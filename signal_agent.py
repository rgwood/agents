#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "claude-agent-sdk",
#     "ddtrace",
#     "python-dotenv",
# ]
# ///

"""
Signal - A Datadog monitoring agent using the Claude Agent SDK.

Analyzes Datadog logs and metrics to generate system health reports.
"""

import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from ddtrace import tracer
from ddtrace.llmobs import LLMObs
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)


# Load environment variables
load_dotenv()

# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
SETTINGS_FILE = SCRIPT_DIR / "agent-settings.json"


# System prompt for the agent
SYSTEM_PROMPT = """You are Signal, a system monitoring agent that uses Datadog observability data.
Your job is to analyze logs and metrics to report on system health.

Unless specified otherwise, report on changes since the last report. If there is no last report, report on the last 24 hours.

You have a working directory where you can read/write files to maintain notes
and read previous reports.

Break reports into 2 sections:
1. Summary - short paragraph for Slack
2. Details - longer analysis for thread

When done, call submit_report with the summary and details.
"""


# Custom tool for submitting reports
@tool("submit_report", "Submit the final report with summary and details sections", {"summary": str, "details": str})
async def submit_report(args: dict[str, Any]) -> dict[str, Any]:
    """Save the report to disk."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_path = REPORTS_DIR / f"{timestamp}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    content = f"## Summary\n\n{args['summary']}\n\n## Details\n\n{args['details']}"
    report_path.write_text(content)

    return {
        "content": [{
            "type": "text",
            "text": f"Report saved to {report_path}"
        }]
    }


# Create the SDK MCP server for custom tools
signal_tools = create_sdk_mcp_server(
    name="signal",
    version="1.0.0",
    tools=[submit_report]
)


async def run_agent(prompt: str) -> str:
    """Run the Signal agent with the given prompt. Returns collected output."""

    # Configure MCP servers
    mcp_servers = {
        "datadog": {
            "type": "http",
            "url": "https://mcp.datadoghq.com/api/unstable/mcp-server/mcp",
            "headers": {
                "DD-API-KEY": os.environ["DD_API_KEY"],
                "DD-APPLICATION-KEY": os.environ["DD_APPLICATION_KEY"]
            }
        },
        "signal": signal_tools
    }

    # Configure agent options - sandbox bash commands and restrict file writes
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        cwd=str(DATA_DIR),
        allowed_tools=[
            "Read", "Write", "Glob", "Bash",
            "mcp__datadog__*",
            "mcp__signal__submit_report"
        ],
        mcp_servers=mcp_servers,
        permission_mode="acceptEdits",
        sandbox={
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "network": {
                "allowLocalBinding": False,
            }
        },
        # Deny writes outside reports/ - use // for absolute paths
        # Patterns: // = absolute, / = relative to settings, ./ = relative to cwd
        settings='{"permissions": {"deny": ["Write(//*)", "Edit(//*)", "Write(~/*)", "Edit(~/*)"], "allow": ["Write(./reports/*)", "Edit(./reports/*)"]}}',
    )

    output_parts = []
    tool_data = {}  # tool_use_id -> {name, input, start_ns, output, end_ns}

    # Run the agent using ClaudeSDKClient (required for SDK MCP servers)
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)

        async for message in client.receive_response():
            # Handle both AssistantMessage and UserMessage (tool results come in UserMessage)
            if isinstance(message, (AssistantMessage, UserMessage)):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        # Only print text from assistant messages
                        if isinstance(message, AssistantMessage):
                            print(block.text)
                            output_parts.append(block.text)

                    elif isinstance(block, ToolUseBlock):
                        # Record tool call start time
                        tool_data[block.id] = {
                            'name': block.name,
                            'input': block.input,
                            'start_ns': time.time_ns(),
                        }

                    elif isinstance(block, ToolResultBlock):
                        # Record tool result and end time
                        if block.tool_use_id in tool_data:
                            tool_data[block.tool_use_id]['output'] = block.content
                            tool_data[block.tool_use_id]['end_ns'] = time.time_ns()

    # Create tool spans after all messages processed (avoids nesting)
    for data in tool_data.values():
        with LLMObs.tool(name=data['name']) as span:
            # Set actual timing on the underlying span
            if hasattr(span, '_span') and span._span is not None:
                span._span.start_ns = data['start_ns']
                span._span.duration_ns = data.get('end_ns', time.time_ns()) - data['start_ns']
            LLMObs.annotate(
                span=span,
                input_data=data['input'],
                output_data=data.get('output')
            )

    return "\n".join(output_parts)


async def main() -> None:
    """Main entry point."""
    # Get prompt from command line or use default
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Report on the last 24 hours."

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize Datadog LLM Observability
    LLMObs.enable(
        ml_app="signal-agent",
        api_key=os.environ["DD_API_KEY"],
        site="datadoghq.com",
        agentless_enabled=True
    )

    try:
        with LLMObs.workflow("signal-session"):
            with LLMObs.agent(name="signal-agent") as agent_span:
                # Annotate with input prompt
                LLMObs.annotate(span=agent_span, input_data=prompt)

                # Run the agent
                output = await run_agent(prompt)

                # Annotate with output
                LLMObs.annotate(span=agent_span, output_data=output)
    finally:
        LLMObs.flush()


if __name__ == "__main__":
    asyncio.run(main())
