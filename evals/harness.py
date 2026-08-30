"""Drive the server's own tools and record what an agent would have seen.

Calls go through `call_tool`, so the eval meets the same argument validation,
the same published schemas and the same JSON text a client is handed. Nothing
here reaches into `sdmx_api` or the other modules directly: a question that
cannot be answered through the tools has not been answered.

Every call is appended to `log/qNN.jsonl` with its arguments, its elapsed time
and the response in full. The finding in an eval is usually that a response did
not say something, which is only checkable against what it did say.
"""

import asyncio
import json
import pathlib
import time

from macro_mcp import server

LOG = pathlib.Path(__file__).parent / "log"

_question = None


def q(number: int, text: str = "") -> None:
    """Start (or continue) a question. Truncates nothing; turns append."""
    global _question
    _question = number
    if text:
        _record({"event": "question", "text": text})


def _record(entry: dict) -> None:
    LOG.mkdir(exist_ok=True)
    path = LOG / f"q{_question:02d}.jsonl"
    with path.open("a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def call(tool: str, /, show: int = 1200, **arguments):
    """One tool call, logged and printed. Returns the parsed response.

    `show` bounds what is printed, never what is logged.
    """
    started = time.monotonic()
    try:
        result = asyncio.run(server.mcp.call_tool(tool, arguments))
        text = result.content[0].text
        failed = None
    except Exception as exc:
        text = ""
        failed = f"{type(exc).__name__}: {exc}"
    elapsed = round(time.monotonic() - started, 2)

    _record({"event": "call", "tool": tool, "arguments": arguments,
             "seconds": elapsed, "bytes": len(text),
             "response": text, "error": failed})

    head = f"--- {tool}({json.dumps(arguments, ensure_ascii=False)})  {elapsed}s"
    if failed:
        print(head + "\n!! " + failed)
        return None
    print(f"{head}  {len(text)}B\n{text[:show]}"
          + ("" if len(text) <= show else f"\n... [{len(text) - show}B more]"))
    return json.loads(text)


def note(text: str) -> None:
    """A judgement the log cannot infer: what the agent concluded, or where it
    is stuck. These are what the write-up is built from."""
    _record({"event": "note", "text": text})
    print("NOTE:", text)
