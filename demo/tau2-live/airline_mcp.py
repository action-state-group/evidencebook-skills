# SPDX-License-Identifier: Apache-2.0
"""The fictional airline's tool server: tau2-bench's 14 airline tools over MCP (stdio).

The tools are tau2-bench's own ``AirlineTools`` (MIT, Sierra Research; pinned in
pyproject.toml) over this case's copy of the booking database, so a write changes
only the case's copy. Two things are added around each call:

- **The policy gate.** tau2's airline policy says the agent must obtain the
  customer's explicit "yes" before any booking-database change. A write tool runs
  only when the customer's latest sealed message is such a confirmation and has not
  already been used for another write; the airline's ``deal check`` reads it, then
  the write runs, then ``deal perform`` seals the act. Without it the tool changes
  nothing and tells the agent to read the action back and ask.
- **The OTel span.** Each call is a span in the case's trace, a child of the
  current turn's span (roleplay.py writes its ``traceparent`` to the case directory). A sealed act's capsule id is stamped on the span with
  capsule-emit's ``stamp_reverse_join`` before the span ends: the span carries a
  reference to the record, never the record (AAC telemetry-binding profile).

Environment: ``TAU2_CASE_DIR`` (the case directory roleplay.py prepared),
``TAU2_STATE`` (the demo's state directory).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

import records
import telemetry

CONFIRM = re.compile(r"\b(yes|yeah|yep|confirm(ed)?|go ahead|please (do|proceed))\b", re.IGNORECASE)


def as_text(result: object) -> str:
    """A tool's result as the agent reads it: tau2 tools return pydantic models,
    lists of them, or plain strings."""
    if hasattr(result, "model_dump_json"):
        return result.model_dump_json()
    if isinstance(result, list):
        return json.dumps([json.loads(as_text(r)) if hasattr(r, "model_dump_json") else r for r in result])
    return result if isinstance(result, str) else json.dumps(result)


def confirmed(text: str) -> bool:
    """Is a customer message an explicit confirmation? A 'no' anywhere voids it."""
    return bool(CONFIRM.search(text)) and not re.search(r"\b(no|don't|do not|wait|stop)\b", text, re.IGNORECASE)


class Airline:
    """The tools of one case, with the gate and the spans."""

    def __init__(self, case_dir: Path, store: records.Store):
        from tau2.domains.airline.data_model import FlightDB
        from tau2.domains.airline.tools import AirlineTools

        self.case_dir = case_dir
        self.db_path = case_dir / "db.json"
        self.db = FlightDB.load(str(self.db_path))
        self.tools = AirlineTools(self.db)
        self.case = records.load_case(store, case_dir)
        self.tracer = telemetry.tracer("airline-tools", case_dir / "spans.jsonl")

    def schemas(self) -> list[types.Tool]:
        out = []
        for name, tool in sorted(self.tools.get_tools().items()):
            fn = tool.openai_schema["function"]
            out.append(types.Tool(name=name, description=fn.get("description", ""), inputSchema=fn["parameters"]))
        return out

    def writes(self, name: str) -> bool:
        return self.tools.tool_type(name).value == "write"

    def confirmation(self) -> dict | None:
        """The customer's latest sealed message, if it confirms and is not yet used."""
        path = self.case_dir / "last_customer.json"
        if not path.exists():
            return None
        msg = json.loads(path.read_text())
        used = self.case_dir / "used_confirmations.json"
        spent = set(json.loads(used.read_text())) if used.exists() else set()
        if msg["capsule_id"] in spent or not confirmed(msg["text"]):
            return None
        return msg

    def spend(self, capsule_id: str) -> None:
        used = self.case_dir / "used_confirmations.json"
        spent = json.loads(used.read_text()) if used.exists() else []
        used.write_text(json.dumps(spent + [capsule_id]))

    def log(self, entry: dict, span=None) -> None:
        entry = dict(entry, at=records.utc(datetime.now(timezone.utc)))
        if span is not None:
            ctx = span.get_span_context()
            entry.update(trace_id=format(ctx.trace_id, "032x"), span_id=format(ctx.span_id, "016x"))
        with (self.case_dir / "tool_calls.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def call(self, name: str, arguments: dict) -> str:
        with self.tracer.start_as_current_span(f"tool {name}", context=telemetry.parent_context(self.case_dir / "traceparent")) as span:
            span.set_attribute("gen_ai.tool.name", name)
            span.set_attribute("tau2.tool.kind", "write" if self.writes(name) else "read")
            if not self.writes(name):
                result = as_text(self.tools.use_tool(name, **arguments))
                self.log({"tool": name, "arguments": arguments, "result": result, "kind": "read"}, span)
                return result
            conf = self.confirmation()
            if conf is None:
                span.set_attribute("tau2.gate", "refused")
                self.log({"tool": name, "arguments": arguments, "kind": "write", "gate": "refused"}, span)
                return ("Not done: the airline policy needs the customer's explicit 'yes' to this exact "
                        "action first. List the action details to the customer and ask them to confirm.")
            check = self.case.check(name, arguments, conf)
            if check.get("verdict") != "pass":
                span.set_attribute("tau2.gate", "check_" + str(check.get("verdict")))
                self.log({"tool": name, "arguments": arguments, "kind": "write", "gate": "check", "check": check}, span)
                return f"Not done: the policy check did not pass ({check.get('verdict')})."
            try:
                result = as_text(self.tools.use_tool(name, **arguments))
            except Exception as err:  # the tool refused (tau2 raises ValueError on bad input)
                self.log({"tool": name, "arguments": arguments, "kind": "write", "error": str(err)}, span)
                return f"Error: {err}"
            self.db.dump(str(self.db_path))
            self.spend(conf["capsule_id"])
            act = self.case.perform(check["check_id"], name)
            telemetry.stamp(span, act["capsule_id"])
            span.set_attribute("tau2.gate", "passed")
            self.log({"tool": name, "arguments": arguments, "result": result, "kind": "write",
                      "confirmation": conf["capsule_id"], "check": check["check_id"], "perform": act["capsule_id"]}, span)
            return result


async def serve() -> None:
    case_dir = Path(os.environ["TAU2_CASE_DIR"])
    store = records.Store(state=Path(os.environ["TAU2_STATE"]))
    airline = Airline(case_dir, store)
    server = Server("tau2-airline")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return airline.schemas()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        try:
            text = airline.call(name, arguments or {})
        except Exception as err:  # report a failure to the agent instead of dropping the session
            text = f"Error: {err}"
        return [types.TextContent(type="text", text=str(text))]

    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(read, write, InitializationOptions(
            server_name="tau2-airline", server_version="0.1.0",
            capabilities=server.get_capabilities(notification_options=NotificationOptions(), experimental_capabilities={})))
    telemetry.shutdown()


if __name__ == "__main__":
    asyncio.run(serve())
