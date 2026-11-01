"""The Dave daemon: DaveBridge's WebSocket on one side, Dave's long-lived claude process on the other.

    python3 -I dave/daemon/main.py            run until SIGTERM/SIGINT (exits non-zero if a core task dies)
    python3 -I dave/daemon/main.py --check    build everything, connect nowhere, print what would run

Standard library only. Contracts: DaveBridge/PROTOCOL.md (game side), dave/ENVELOPE.md (Claude side).

One claude process (dave_cmd.build(mode="stream")) answers every player, one turn at a time:
  chat event -> queue (cooldowns, caps) -> envelope (profile from memory) -> stdin -> `result` -> say.
The session rotates every [session] rotate_turns turns / rotate_hours hours; a crash (during a turn or between
turns) resumes the same session once, then starts fresh. Every top-level `result` goes through one queue: a turn
takes its own result from it, a background recipe-planner run holds the queue until its follow-up answer is taken
from it, and a result nobody is waiting for goes to the player of the last turn. So a late answer always goes to
the player who asked.
"""

import asyncio
import collections
import json
import logging
import logging.handlers
import os
import re
import signal
import sys
import time
import uuid as uuidlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dave import config  # noqa: E402
from dave.daemon import envelope  # noqa: E402
from dave.daemon.ws import ConnectionClosed, HandshakeError, WebSocket  # noqa: E402
from dave.launch import dave_cmd  # noqa: E402
from dave.memory import store as memstore  # noqa: E402

log = logging.getLogger("dave")

NOTICE_BUSY = "Dave has a long line of questions right now. Try again in a minute."
NOTICE_ONE_AT_A_TIME = "One at a time, please! I'll get to your earlier question first."
NOTICE_CRASH = "Sorry, I lost my train of thought there. Could you ask that again?"
NOTICE_TIMEOUT = "Sorry, that one took me too long and I had to give up on it. Try asking a smaller piece of it?"
NOTICE_ERROR = "Sorry, something went wrong on my end. Try again in a bit."
NOTICE_LIMIT = "I'm out of steam for now (usage limit). Try again later!"
NOTICE_STALE = "Sorry, I lost the connection to the server and your question waited too long. Could you ask again?"

SESSION_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_-]{7,80}$")


def setting(cfg, section, key, default, cast=int):
    try:
        return cast(cfg.get(section, {}).get(key, default))
    except (TypeError, ValueError):
        return default


def spawn(coro, name, keep):
    """Runs coro as a task whose failure is logged, holding a reference in `keep` until it ends."""
    async def guarded():
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s failed", name)
    task = asyncio.create_task(guarded())
    keep.add(task)
    task.add_done_callback(keep.discard)
    return task


# ------------------------------------------------------------------------------------------------ bridge

class BridgeDown(Exception):
    pass


class Bridge:
    """Keeps one authenticated connection to DaveBridge, reconnecting with backoff. Events go to on_event."""

    def __init__(self, url, token, on_event, ping_seconds=30, missed_pings=3):
        self.url, self.token, self.on_event, self.ping_seconds = url, token, on_event, ping_seconds
        self.ping_timeout = min(15, ping_seconds)
        self.missed_pings = max(1, missed_pings)   # this many unanswered pings in a row: drop and reconnect
        self.ws = None
        self.hello = None
        self.ready = asyncio.Event()
        self._pending = {}
        self._handlers = set()
        self._req = 0
        self._last_tick = None

    async def run(self):
        delays = [1, 2, 5, 10, 30]
        attempt = 0
        while True:
            try:
                self.ws = await WebSocket.connect(self.url, headers={"Authorization": "Bearer " + self.token})
                first = json.loads(await asyncio.wait_for(self.ws.recv(), 15))
                if not isinstance(first, dict) or first.get("type") != "hello":
                    raise HandshakeError("expected hello, got %s" % (first.get("type") if isinstance(first, dict)
                                                                     else type(first).__name__))
                self.hello, attempt = first, 0
                log.info("bridge connected: %s %s, protocol %s, accepts %s", first.get("mod"), first.get("version"),
                         first.get("protocol"), first.get("accepts"))
                self.ready.set()
                pinger = asyncio.create_task(self._keepalive(self.ws))
                try:
                    while True:
                        raw = await self.ws.recv()
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            log.warning("bridge sent a frame that is not JSON; ignored")
                            continue
                        if not isinstance(msg, dict):
                            log.warning("bridge sent a %s, not an object; ignored", type(msg).__name__)
                            continue
                        self._dispatch(msg)
                finally:
                    pinger.cancel()
            except asyncio.CancelledError:
                raise
            except (OSError, ConnectionClosed, HandshakeError, asyncio.TimeoutError, ValueError) as e:
                log.warning("bridge: %s", e)
            finally:
                self.ready.clear()
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(BridgeDown("connection lost"))
                self._pending.clear()
                if self.ws:
                    await self.ws.close()
                    self.ws = None
            delay = delays[min(attempt, len(delays) - 1)]
            attempt += 1
            log.info("bridge: reconnecting in %ss", delay)
            await asyncio.sleep(delay)

    def _dispatch(self, msg):
        rid = msg.get("reqId")
        try:
            fut = self._pending.pop(rid, None) if rid is not None else None
        except TypeError:                       # an unhashable reqId is never one of ours
            fut = None
        if fut is not None:
            if not fut.done():
                fut.set_result(msg)
            return
        if msg.get("type") == "error":
            log.warning("bridge error: %s %s", msg.get("code"), msg.get("message"))
            return
        # Handlers run as their own tasks: they send requests whose replies arrive through this read loop, so
        # awaiting them here would deadlock. Tasks start in creation order, and a handler queues its turn before
        # its first await, so turn order still follows event order.
        spawn(self.on_event(msg), "event handler for %s" % msg.get("type"), self._handlers)

    async def request(self, msg, timeout=30):
        """Sends a request and returns the server's reply (ack, error, pong, players...)."""
        if not self.ws or not self.ready.is_set():
            raise BridgeDown("not connected")
        self._req += 1
        rid = self._req
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self.ws.send(json.dumps(dict(msg, reqId=rid)))
            return await asyncio.wait_for(fut, timeout)
        except ConnectionClosed as e:
            raise BridgeDown(str(e)) from e
        finally:
            self._pending.pop(rid, None)

    async def _keepalive(self, ws):
        missed = 0
        while True:
            await asyncio.sleep(self.ping_seconds)
            try:
                pong = await self.request({"type": "ping"}, timeout=self.ping_timeout)
            except (BridgeDown, asyncio.TimeoutError):
                missed += 1
                log.warning("bridge: ping unanswered (%d in a row)", missed)
                if missed >= self.missed_pings:
                    # A half-open connection never errors on its own: drop it so the read loop reconnects.
                    log.warning("bridge: no pong %d times; dropping the connection", missed)
                    ws.abort()
                    return
                continue
            missed = 0
            tick = pong.get("tick")
            if tick is not None and tick == self._last_tick:
                log.warning("bridge: server tick stuck at %s (queue depth %s)", tick, pong.get("queueDepth"))
            self._last_tick = tick

    async def say(self, target, markup=None, text=None, reply_to=None):
        msg = {"type": "say", "target": target}
        msg.update({"markup": markup} if markup is not None else {"text": text})
        if reply_to:
            msg["replyTo"] = reply_to
        return await self.request(msg)

    async def notice(self, player, text):
        """A private plain-text line to one player. Best effort."""
        try:
            await self.say(player, text=text)
        except (BridgeDown, asyncio.TimeoutError):
            pass

    async def thinking(self, player):
        try:
            await self.request({"type": "thinking", "target": player}, timeout=10)
        except (BridgeDown, asyncio.TimeoutError):
            pass


# ------------------------------------------------------------------------------------------------ claude

class ClaudeDied(Exception):
    pass


class Claude:
    """Dave's long-lived stream-json process.

    Every top-level `result` event goes to one place: the results queue while the daemon owns it (`busy`, set for
    a turn and its follow-ups), or on_late_result when nobody is waiting. ask() sends one envelope and returns the
    next result from the queue; wait_followup() takes the next one after a background agent was launched.
    """

    def __init__(self, cfg, on_late_result, line_limit=32 * 1024 * 1024):
        self.cfg = cfg
        self.on_late_result = on_late_result
        self.line_limit = line_limit
        self.proc = None
        self.session_id = None
        self.resumed = False           # the current process was started with --resume
        self.crashed_session = None    # session of a process that exited on its own (not via stop())
        self.started = 0.0
        self.turns = 0
        self.background = 0            # background agents launched and not yet followed up
        self.busy = False
        self.results = asyncio.Queue()
        self._tasks = []
        self._late = set()

    @property
    def alive(self):
        return self.proc is not None and self.proc.returncode is None

    async def start(self, resume=None):
        """Starts the process. A resume keeps the session's turn count and age, so rotation stays on schedule."""
        b = dave_cmd.build(self.cfg, mode="stream", resume=resume)
        if b["problems"]:
            raise RuntimeError("refusing to start Dave: " + "; ".join(b["problems"]))
        if not b["token_source"]:
            raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN is not available (env, NAME_FILE, /run/secrets or dave/.env)")
        self.proc = await asyncio.create_subprocess_exec(
            *b["argv"], cwd=str(b["cwd"]), env=b["env"], stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=self.line_limit)
        self.session_id, self.resumed, self.crashed_session = resume, bool(resume), None
        if not resume:
            self.started, self.turns = time.monotonic(), 0
        self.background = 0
        self.results = asyncio.Queue()
        self._tasks = [asyncio.create_task(self._read_stdout(self.proc, self.results)),
                       asyncio.create_task(self._read_stderr(self.proc))]
        log.info("claude started (pid %s%s, model %s)", self.proc.pid,
                 ", resuming " + resume if resume else "", self.cfg["model"]["name"])

    async def stop(self, graceful=True):
        """Ends the process: closes stdin and waits (graceful), or terminates it straight away (a hung turn)."""
        proc, self.proc = self.proc, None
        self.crashed_session = None
        if proc and proc.returncode is None:
            try:
                proc.stdin.close()
                await asyncio.wait_for(proc.wait(), 10 if graceful else 0.5)
            except (asyncio.TimeoutError, OSError):
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    def take_crashed(self):
        """The session of a process that died on its own since the last start/stop, once."""
        sid, self.crashed_session = self.crashed_session, None
        return sid

    async def ask(self, content, timeout):
        if not self.alive:
            raise ClaudeDied("not running")
        results = self.results
        line = json.dumps(envelope.user_message(content)) + "\n"
        try:
            self.proc.stdin.write(line.encode("utf-8"))
            await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise ClaudeDied("stdin closed") from e
        self.turns += 1
        return await self._next(results, timeout)

    async def wait_followup(self, timeout):
        """After a turn that launched a background agent: the next top-level result."""
        return await self._next(self.results, timeout)

    @staticmethod
    async def _next(results, timeout):
        item = await asyncio.wait_for(results.get(), timeout)
        if isinstance(item, BaseException):
            results.put_nowait(item)             # the process is gone: every later wait sees it too
            raise item
        return item

    def drain(self):
        """Results queued but not taken (a turn's extra answers). The process-exit marker stays queued."""
        out, keep = [], []
        while not self.results.empty():
            item = self.results.get_nowait()
            (keep if isinstance(item, BaseException) else out).append(item)
        for item in keep:
            self.results.put_nowait(item)
        return out

    def session_has(self, text, session_id=None):
        """True if the session's transcript (CLAUDE_CONFIG_DIR/projects/*/<id>.jsonl) contains `text`.

        Used after a crash: a turn id found there means the CLI already took that envelope, so it is not sent twice.
        """
        sid = session_id or self.session_id
        if not sid or not SESSION_ID_RE.match(sid):
            return False
        for p in (Path(self.cfg["paths"]["claude_home"]) / "projects").glob("*/%s.jsonl" % sid):
            try:
                if text in p.read_text(encoding="utf-8", errors="replace"):
                    return True
            except OSError:
                continue
        return False

    def _on_event(self, ev, results):
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            self.session_id = ev.get("session_id") or self.session_id
        # A backgrounded agent finishes after the turn's result and makes Dave answer again (a second
        # result). Foreground runs (the planner's normal case) report is_backgrounded false.
        if ev.get("type") == "system" and ev.get("subtype") == "task_started" and ev.get("is_backgrounded"):
            self.background += 1
        if ev.get("parent_tool_use_id"):
            return                               # the planner's own events
        if ev.get("type") == "result":
            self.session_id = ev.get("session_id") or self.session_id
            if self.busy:
                results.put_nowait(ev)
            else:
                if self.background > 0:
                    self.background -= 1
                spawn(self.on_late_result(ev), "late result delivery", self._late)

    async def _read_stdout(self, proc, results):
        try:
            while True:
                try:
                    raw = await proc.stdout.readline()
                except ValueError:               # a line longer than line_limit: the reader skips it
                    log.warning("claude: skipped an output line over %d bytes", self.line_limit)
                    continue
                if not raw:
                    break
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(ev, dict):
                    continue
                try:
                    self._on_event(ev, results)
                except Exception:
                    log.exception("claude: could not handle a %s event; skipped", ev.get("type"))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Without a reader the process would block on a full pipe and every turn would wait out its
            # timeout: end it now so the turn fails over to the crash path at once.
            log.exception("claude: stdout reader failed; stopping the process")
            if proc.returncode is None:
                proc.kill()
        finally:
            rc = await proc.wait()
            results.put_nowait(ClaudeDied("exited with %s" % rc))
            if proc is self.proc:
                self.crashed_session = self.session_id
                log.warning("claude exited with %s", rc)

    async def _read_stderr(self, proc):
        while True:
            try:
                raw = await proc.stderr.readline()
            except ValueError:
                continue
            if not raw:
                return
            log.info("claude stderr: %s", raw.decode("utf-8", "replace").rstrip()[:500])


# ------------------------------------------------------------------------------------------------ daemon

class Turn:
    def __init__(self, chat):
        self.chat = chat
        self.player = chat.get("player") or "?"
        self.uuid = chat.get("playerUuid") or ""
        # The per-player cap and cooldown key: the UUID, or the name when the bridge sent no UUID.
        self.key = self.uuid or "name:" + self.player.lower()
        self.enqueued = time.monotonic()
        self.id = "t-" + uuidlib.uuid4().hex[:10]


class Daemon:
    def __init__(self, cfg):
        self.cfg = cfg
        s = lambda k, d, c=int: setting(cfg, "session", k, d, c)  # noqa: E731
        self.rotate_turns, self.rotate_hours = s("rotate_turns", 40), s("rotate_hours", 6, float)
        self.turn_timeout, self.followup_timeout = s("turn_timeout_seconds", 600), s("followup_timeout_seconds", 900)
        self.cooldown, self.max_per_player = s("cooldown_seconds", 4, float), s("max_per_player", 2)
        self.max_queue, self.stale = s("max_queue", 10), s("stale_seconds", 300, float)
        self.default_target = cfg.get("session", {}).get("default_target", "reply")
        self.pack = cfg["pack"]["version"]
        token, src = config.secret(cfg, "bridge_token")
        if not token:
            raise RuntimeError("DaveBridge token not found (DAVE_BRIDGE_TOKEN, _FILE, /run/secrets/dave_token or dave/.env)")
        self.bridge = Bridge(cfg["bridge"]["url"], token, self.on_event, setting(cfg, "bridge", "ping_seconds", 30),
                             setting(cfg, "bridge", "missed_pings", 3))
        self.claude = Claude(cfg, self.on_late_result)
        self.store = memstore.open_store(cfg, actor="daemon")
        self.queue = collections.deque()
        self.wakeup = asyncio.Event()
        self.in_flight = None
        self.free_since = 0.0                  # when the worker last finished a turn (waiting behind Dave isn't stale)
        self.last_ask = {}                     # player key -> monotonic time of their last accepted ask
        self.client_eval = {}                  # uuid -> clientEvalAllowed from client_mod
        self.warnings = []                     # (turn id, text) from the last say ack, for the next turn
        self.recent = collections.deque(maxlen=6)
        self.fresh_session = True              # next turn is the first of a session: add <recent>
        self.last_turn = None                  # the turn a late (background) result belongs to
        logs = log_dir(cfg)
        logs.mkdir(parents=True, exist_ok=True)
        self.transcript = logs / "turns.jsonl"
        self.log_max_bytes = int(setting(cfg, "logs", "max_mb", 10, float) * 1024 * 1024)
        self.log_keep = setting(cfg, "logs", "keep", 5)

    # ---- events

    async def on_event(self, ev):
        t = ev.get("type")
        if t == "chat":
            await self.on_chat(ev)
        elif t == "client_mod":
            self.client_eval[ev.get("playerUuid")] = bool(ev.get("clientEvalAllowed"))
        elif t == "player_leave":
            self.client_eval.pop(ev.get("playerUuid"), None)
        elif t == "server_stopping":
            log.info("server stopping; waiting for it to come back")

    async def on_chat(self, ev):
        if not ev.get("triggered"):
            return
        turn = Turn(ev)
        key, name = turn.key, ev.get("player")
        mine = sum(1 for q in self.queue if q.key == key) + (1 if self.in_flight and self.in_flight.key == key else 0)
        now = time.monotonic()
        if mine >= self.max_per_player or (mine and now - self.last_ask.get(key, 0) < self.cooldown):
            await self.bridge.notice(name, NOTICE_ONE_AT_A_TIME)
            return
        if len(self.queue) >= self.max_queue:
            await self.bridge.notice(name, NOTICE_BUSY)
            return
        if len(self.last_ask) > 500:           # forget players who have not asked for a while
            self.last_ask = {k: v for k, v in self.last_ask.items() if now - v < 3600}
        self.last_ask[key] = now
        self.queue.append(turn)
        self.wakeup.set()
        await self.bridge.thinking(name)

    async def on_late_result(self, ev):
        """A top-level result with no turn waiting for it (an unannounced second answer, between turns)."""
        log.warning("late result with no waiting turn; delivering to %s", self.last_turn.player if self.last_turn else "nobody")
        if self.last_turn:
            await self.deliver(self.last_turn, ev, late=True)

    # ---- the worker

    async def worker(self):
        while True:
            if not self.queue:
                self.wakeup.clear()
                await self.wakeup.wait()
                continue
            await self.bridge.ready.wait()
            turn = self.queue.popleft()
            # Only time spent waiting while Dave was free counts (i.e. the bridge was down): a question queued
            # behind a long planner turn is not stale.
            waited = time.monotonic() - max(turn.enqueued, self.free_since)
            if waited > self.stale:
                log.info("dropping stale question from %s (waited %.0f s for the bridge)", turn.player, waited)
                await self.bridge.notice(turn.player, NOTICE_STALE)
                continue
            self.in_flight = turn
            try:
                await self.run_turn(turn)
            except Exception:
                log.exception("turn %s failed", turn.id)
                await self.bridge.notice(turn.player, NOTICE_ERROR)
            finally:
                self.in_flight = None
                self.free_since = time.monotonic()

    async def ensure_claude(self):
        age_h = (time.monotonic() - self.claude.started) / 3600
        if self.claude.alive and (self.claude.turns >= self.rotate_turns or age_h >= self.rotate_hours):
            log.info("rotating session after %d turns / %.1f h", self.claude.turns, age_h)
            await self.claude.stop()
            self.fresh_session = True
        if not self.claude.alive:
            resume = self.claude.take_crashed()  # died between turns: pick the same session up again
            await self.claude.stop()
            if resume:
                log.info("claude died between turns; resuming session %s", resume)
            else:
                self.fresh_session = True
            await self.claude.start(resume=resume)

    async def run_turn(self, turn):
        await self.ensure_claude()
        chat = turn.chat
        prompt = chat.get("prompt") if chat.get("triggered") else chat.get("message")
        if turn.uuid:
            await asyncio.to_thread(self.store.ensure_player, turn.uuid, turn.player, "daemon")
        profile = await asyncio.to_thread(memstore.load_turn_context, turn.uuid, prompt, turn.player, 1500, self.store)
        content = envelope.build(turn.id, chat, profile, self.pack, client_eval=self.client_eval.get(turn.uuid),
                                 warnings=self.warnings, recent=list(self.recent) if self.fresh_session else None)
        previous = self.last_turn
        self.warnings, self.fresh_session, self.last_turn = [], False, turn
        self.claude.busy = True
        try:
            for stray in self.claude.drain():    # an answer that arrived before this turn: not this player's
                if previous:
                    await self.deliver(previous, stray, late=True)
            await self._run_turn_owned(turn, content)
        finally:
            for extra in self.claude.drain():    # a second answer to this turn that nobody announced
                await self.deliver(turn, extra, late=True)
            self.claude.busy = False

    async def _run_turn_owned(self, turn, content):
        heartbeat = asyncio.create_task(self._thinking_heartbeat(turn.player))
        started = time.monotonic()
        try:
            result = await self._ask_with_recovery(turn, content)
        finally:
            heartbeat.cancel()
        if result is None:
            return
        await self.deliver(turn, result, started=started)
        while self.claude.background > 0 and self.claude.alive:
            log.info("background agent running for %s; holding the queue for its follow-up", turn.player)
            heartbeat = asyncio.create_task(self._thinking_heartbeat(turn.player))
            try:
                follow = await self.claude.wait_followup(self.followup_timeout)
            except (asyncio.TimeoutError, ClaudeDied) as e:
                log.warning("no follow-up from the background agent (%s); restarting the session", type(e).__name__)
                await self.claude.stop(graceful=False)
                self.fresh_session = True
                break
            finally:
                heartbeat.cancel()
            self.claude.background -= 1
            await self.deliver(turn, follow, late=True)

    async def _ask_with_recovery(self, turn, content):
        try:
            return await self.claude.ask(content, self.turn_timeout)
        except asyncio.TimeoutError:
            log.warning("turn %s timed out after %ss; restarting the session", turn.id, self.turn_timeout)
            await self.bridge.notice(turn.player, NOTICE_TIMEOUT)
            await self.claude.stop(graceful=False)
            self.fresh_session = True
            return None
        except ClaudeDied as e:
            # Resume once. A process that was itself a resume and died again starts fresh instead.
            sid = None if self.claude.resumed else self.claude.session_id
            log.warning("claude died during turn %s (%s); %s", turn.id, e, "resuming once" if sid else "restarting fresh")
            await self.claude.stop()
            try:
                await self.claude.start(resume=sid)
                if not sid:
                    self.fresh_session = True
                if sid and self.claude.session_has(turn.id, sid):
                    # The CLI already took this envelope before it died: the resumed session has the question,
                    # so ask for the answer instead of sending the question twice.
                    log.info("session %s already has turn %s; sending a retry nudge", sid, turn.id)
                    content = envelope.retry(turn.id, turn.chat, self.pack)
                return await self.claude.ask(content, self.turn_timeout)
            except Exception as e2:              # noqa: BLE001 - any second failure: fresh session, apologise
                log.warning("retry failed (%s); starting a fresh session", e2)
                await self.claude.stop()
                self.fresh_session = True
                await self.bridge.notice(turn.player, NOTICE_CRASH)
                return None

    async def _thinking_heartbeat(self, player):
        while True:
            await asyncio.sleep(45)               # the client half drops the line after 60 s
            await self.bridge.thinking(player)

    async def deliver(self, turn, result, started=None, late=False):
        text = result.get("result") or ""
        if result.get("is_error") or result.get("subtype", "success") != "success":
            limit = "limit" in text.lower() or "usage" in text.lower()
            log.warning("turn %s ended with %s: %s", turn.id, result.get("subtype"), text[:300])
            await self.bridge.notice(turn.player, NOTICE_LIMIT if limit else NOTICE_ERROR)
            self._record(turn, result, "error", text, None, started, late)
            return
        directive, markup, had = envelope.parse_reply(text, self.default_target)
        if not had:
            log.info("turn %s: no directive on line 1; using %s", turn.id, self.default_target)
        ack = None
        if directive != "none" and markup:
            target = "@a" if directive == "reply" else turn.player
            try:
                ack = await self.bridge.say(target, markup=markup, reply_to=turn.chat.get("id"))
            except (BridgeDown, asyncio.TimeoutError) as e:
                log.warning("could not post the reply for %s: %s", turn.id, e)
            if ack and ack.get("type") == "error":
                log.warning("say refused for %s: %s %s", turn.id, ack.get("code"), ack.get("message"))
            for w in (ack or {}).get("warnings") or []:
                self.warnings.append((turn.id, w))
            # <recent> is public chat only: never a whisper, nor an Ask from the client half (others never see it).
            if target == "@a" and (turn.chat.get("source") or "chat") == "chat":
                self.recent.append("%s: %s" % (turn.player, (turn.chat.get("prompt") or turn.chat.get("message") or "")[:150]))
                self.recent.append("Dave: %s" % markup.replace("\n", " ")[:150])
        self._record(turn, result, directive, markup, ack, started, late)

    def _record(self, turn, result, directive, reply, ack, started, late):
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "turn": turn.id, "player": turn.player, "uuid": turn.uuid,
               "source": turn.chat.get("source"), "prompt": turn.chat.get("prompt") or turn.chat.get("message"),
               "directive": directive, "reply": reply, "late": late,
               "seconds": round(time.monotonic() - started, 1) if started else None,
               "session": result.get("session_id"), "num_turns": result.get("num_turns"),
               "cost_usd": result.get("total_cost_usd"),
               "warnings": (ack or {}).get("warnings"), "recipients": (ack or {}).get("recipients")}
        try:
            rotate_file(self.transcript, self.log_max_bytes, self.log_keep)
            with open(self.transcript, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:                      # a full disk must not cost the player their answer
            log.warning("could not write the transcript: %s", e)
        log.info("turn %s %s -> %s (%s s)%s", turn.id, turn.player, directive, row["seconds"], " [late]" if late else "")

    # ---- lifecycle

    async def run(self):
        """Runs until SIGTERM/SIGINT (returns 0) or until the bridge or worker task dies (logs it, returns 1)."""
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        signals = (signal.SIGTERM, signal.SIGINT)
        for sig in signals:
            loop.add_signal_handler(sig, stop.set)
        tasks = {asyncio.create_task(self.bridge.run(), name="bridge"),
                 asyncio.create_task(self.worker(), name="worker")}
        stopper = asyncio.create_task(stop.wait(), name="stop")
        rc = 0
        try:
            await self.claude.start()
            done, _ = await asyncio.wait(tasks | {stopper}, return_when=asyncio.FIRST_COMPLETED)
            for t in done - {stopper}:
                rc = 1
                exc = None if t.cancelled() else t.exception()
                if exc:
                    log.critical("the %s task died; exiting so the container restarts", t.get_name(),
                                 exc_info=(type(exc), exc, exc.__traceback__))
                else:
                    log.critical("the %s task ended unexpectedly; exiting so the container restarts", t.get_name())
            log.info("shutting down")
        finally:
            for t in tasks | {stopper}:
                t.cancel()
            await asyncio.gather(*tasks, stopper, return_exceptions=True)
            await self.claude.stop()
            if self.bridge.ws:
                await self.bridge.ws.close(1001)
            for sig in signals:
                loop.remove_signal_handler(sig)
        return rc


def log_dir(cfg):
    """Where turns.jsonl and daemon.log go: [paths] logs (a volume in production), else <run>/daemon."""
    return cfg["paths"].get("logs") or cfg["paths"]["run"] / "daemon"


def rotate_file(path, max_bytes, keep):
    """Size-based rotation like logging's RotatingFileHandler: path -> path.1 -> ... -> path.<keep>."""
    try:
        if max_bytes <= 0 or path.stat().st_size < max_bytes:
            return
    except FileNotFoundError:
        return
    for i in range(keep - 1, 0, -1):
        src = path.with_name("%s.%d" % (path.name, i))
        if src.exists():
            os.replace(src, path.with_name("%s.%d" % (path.name, i + 1)))
    if keep > 0:
        os.replace(path, path.with_name(path.name + ".1"))
    else:
        path.unlink()


def setup_logging(cfg):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(fmt)
    log.addHandler(h)
    d = log_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        d / "daemon.log", encoding="utf-8", maxBytes=int(setting(cfg, "logs", "max_mb", 10, float) * 1024 * 1024),
        backupCount=setting(cfg, "logs", "keep", 5))
    fh.setFormatter(fmt)
    log.addHandler(fh)


def check(cfg):
    b = dave_cmd.build(cfg, mode="stream")
    _, bridge_src = config.secret(cfg, "bridge_token")
    print("claude:   %s" % " ".join(b["argv"][:3]) + " ...")
    print("token:    %s" % (b["token_source"] or "MISSING"))
    print("bridge:   %s (token %s)" % (cfg["bridge"]["url"], bridge_src or "MISSING"))
    print("memory:   %s" % cfg["paths"]["memory"])
    print("log:      %s" % log_dir(cfg))
    for p in b["problems"]:
        print("PROBLEM:  " + p)
    ok = not b["problems"] and b["token_source"] and bridge_src
    print("CHECK " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv):
    cfg = config.load()
    if "--check" in argv:
        return check(cfg)
    setup_logging(cfg)
    return asyncio.run(Daemon(cfg).run())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
