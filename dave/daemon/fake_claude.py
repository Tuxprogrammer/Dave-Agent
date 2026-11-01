#!/usr/bin/env python3
"""Test double for `claude -p --input-format stream-json --output-format stream-json`. Used by test_daemon.py.

Reads one user message per stdin line and answers by keyword in the envelope's <message>:
  CRASH    exit(3) without answering, after recording the message in the session (only the first time per test)
  EARLYCRASH  the same, but before the message reaches the session transcript
  SLOW     sleep 30 s before answering         PAUSE  sleep 1 s before answering
  BG       launch a "background agent": answer "@reply\\nOn it", then a follow-up result 0.5 s later
  BGFAST   the same with the follow-up written straight after the first result (no delay)
  BGQUIET  a second result 0.5 s later with no task_started announcing it
  JUNK     emit non-object JSON lines and an over-long line before answering
  WHISPER  "@whisper\\n..."     NONE  "@none"     NODIR  an answer with no directive line
  ERROR    a result with is_error
otherwise "@reply\\nhello <player>" plus flags: "warn" if the envelope had <warnings>, "recent" if <recent>.
A kind="retry" envelope (after a crash) is answered "hello <player> (retry)".
Every received envelope is appended to <cwd>/../fake/envelopes.jsonl, every start to starts.jsonl, and (like
the real CLI) to the session transcript $CLAUDE_CONFIG_DIR/projects/fake/<session>.jsonl.
"""

import json
import os
import re
import sys
import time
import uuid

# dave_cmd passes only an allowlisted environment, so the state dir comes from the cwd (the test's workdir).
state = os.path.join(os.path.dirname(os.getcwd()), "fake")
os.makedirs(state, exist_ok=True)
resume = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else None
session = resume or str(uuid.uuid4())
with open(os.path.join(state, "starts.jsonl"), "a") as f:
    f.write(json.dumps({"resume": resume, "session": session, "pid": os.getpid()}) + "\n")
transcript = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", state), "projects", "fake", session + ".jsonl")
os.makedirs(os.path.dirname(transcript), exist_ok=True)


def emit(ev):
    sys.stdout.write(json.dumps(ev) + "\n")
    sys.stdout.flush()


def result(text, is_error=False):
    emit({"type": "result", "subtype": "success", "is_error": is_error, "result": text, "session_id": session,
          "num_turns": 1, "total_cost_usd": 0.0})


emit({"type": "system", "subtype": "init", "session_id": session, "model": "fake"})
for line in sys.stdin:
    try:
        content = json.loads(line)["message"]["content"]
    except (ValueError, KeyError, TypeError):
        continue
    with open(os.path.join(state, "envelopes.jsonl"), "a") as f:
        f.write(json.dumps(content) + "\n")
    name = re.search(r'<player name="([^"]*)"', content).group(1)
    if 'kind="retry"' in content:
        result("@reply\nhello " + name + " (retry)")
        continue
    msg = re.search(r"<message>(.*)</message>", content, re.S).group(1)
    crashed = os.path.join(state, "crashed")
    if "EARLYCRASH" in msg and not os.path.exists(crashed):
        open(crashed, "w").close()
        sys.exit(3)
    with open(transcript, "a") as f:
        f.write(json.dumps({"type": "user", "sessionId": session, "message": {"role": "user", "content": content}}) + "\n")
    if "CRASH" in msg and not os.path.exists(crashed):
        open(crashed, "w").close()
        sys.exit(3)
    if "SLOW" in msg:
        time.sleep(30)
    if "PAUSE" in msg:
        time.sleep(1)
    if "JUNK" in msg:
        sys.stdout.write("[1, 2]\n\"just a string\"\nnot json at all\n")
        sys.stdout.write(json.dumps({"type": "assistant", "pad": "x" * 5000}) + "\n")
        sys.stdout.flush()
    if "BGQUIET" in msg:
        result("@reply\nfirst, " + name)
        time.sleep(0.5)
        result("@reply\nunannounced second, " + name)
        continue
    if "BG" in msg:
        fast = "BGFAST" in msg
        emit({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "tu1", "name": "Agent", "input": {"subagent_type": "recipe-planner"}}]}})
        emit({"type": "system", "subtype": "task_started", "task_id": "bg1", "tool_use_id": "tu1",
              "subagent_type": "recipe-planner", "is_backgrounded": True})
        emit({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": [{"type": "text", "text": "Async agent launched successfully."}]}]}})
        emit({"type": "assistant", "parent_tool_use_id": "tu1", "message": {"content": [{"type": "text", "text": "planner chatter"}]}})
        result("@reply\nOn it, " + name)
        if not fast:
            time.sleep(0.5)
        result("@reply\nPlanner says: air centrifuge, " + name)
        continue
    if "WHISPER" in msg:
        result("@whisper\npsst " + name)
    elif "NONE" in msg:
        result("@none")
    elif "NODIR" in msg:
        result("no directive for " + name)
    elif "ERROR" in msg:
        result("Claude usage limit reached", is_error=True)
    else:
        flags = [w for w, tag in (("warn", "<warnings"), ("recent", "<recent>")) if tag in content]
        result("@reply\nhello " + name + (" [" + ",".join(flags) + "]" if flags else ""))
