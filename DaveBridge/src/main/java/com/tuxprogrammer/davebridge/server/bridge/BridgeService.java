package com.tuxprogrammer.davebridge.server.bridge;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.java_websocket.WebSocket;
import org.java_websocket.framing.CloseFrame;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.Tags;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.common.tasks.MainThreadQueue;

/**
 * Lifecycle and session management for the agent WebSocket. Thread-safe: start/stop/applyConfig run on the server
 * thread, session callbacks on socket threads, {@link #broadcast} from anywhere.
 * <p>
 * Two locks: {@code lifecycle} serializes start/stop/applyConfig (and is held while stopping joins the selector
 * thread); the service monitor only guards the fields and is never held while waiting for a socket thread, because
 * socket threads take it in {@link #onServerError}.
 */
public final class BridgeService {

    private final MainThreadQueue queue;
    private final MessageRouter router;
    private final Set<ClientSession> sessions = ConcurrentHashMap.newKeySet();
    private final AtomicInteger nextSessionId = new AtomicInteger();

    private volatile BridgeServer server;
    private volatile boolean listening;
    private volatile String lastError;
    private volatile int serverTick;
    /** Set when the server is stopping: agent messages then get {@code cancelled} instead of being queued. */
    private volatile boolean stopping;
    private final Object lifecycle = new Object();
    private String runningSettings;
    private ScheduledExecutorService scheduler;

    public BridgeService(MainThreadQueue queue) {
        this.queue = queue;
        this.router = new MessageRouter(queue);
        router.register("ping", this::handlePing);
    }

    public MessageRouter router() {
        return router;
    }

    // ---- lifecycle (server thread) ----

    public void start() {
        synchronized (lifecycle) {
            startLocked();
        }
    }

    private synchronized void startLocked() {
        if (server != null) {
            return;
        }
        if (!Config.enabled) {
            DaveBridge.LOG.info("Agent bridge disabled in config");
            return;
        }
        lastError = null;
        stopping = false;
        scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "DaveBridge-timer");
            t.setDaemon(true);
            return t;
        });
        InetSocketAddress address = new InetSocketAddress(Config.bindAddress, Config.port);
        BridgeServer s = new BridgeServer(address, this, Config.maxClients, Config.maxMessageBytes);
        server = s;
        runningSettings = currentSettings();
        s.start();
        DaveBridge.LOG.info("Starting agent bridge on ws://{}:{}", Config.bindAddress, Config.port);
    }

    /**
     * First step of a server shutdown: from now on agent messages are answered with {@code cancelled} instead of being
     * queued. The caller then fails the queued tasks (their errors still reach the agent) and calls {@link #stop}.
     */
    public void beginStopping() {
        stopping = true;
    }

    public void stop() {
        synchronized (lifecycle) {
            stopLocked();
        }
    }

    private void stopLocked() {
        BridgeServer s;
        ScheduledExecutorService timer;
        synchronized (this) {
            stopping = true;
            s = server;
            timer = scheduler;
            server = null;
            scheduler = null;
            listening = false;
            runningSettings = null;
        }
        // Outside the service monitor: stop() joins the selector thread, which may itself call back into this service.
        if (s != null) {
            try {
                for (ClientSession session : sessions) {
                    if (session.isAuthenticated()) {
                        session.send(Protocol.message("server_stopping"));
                    }
                }
                s.stop(2000, "server stopping");
            } catch (InterruptedException e) {
                Thread.currentThread()
                    .interrupt();
            } catch (Throwable t) {
                DaveBridge.LOG.warn("Error stopping agent bridge", t);
            }
            DaveBridge.LOG.info("Agent bridge stopped");
        }
        sessions.clear();
        if (timer != null) {
            timer.shutdownNow();
        }
    }

    /** After a config reload: restart if network settings changed, or start/stop if enablement changed. */
    public void applyConfig(boolean allowedOnThisServer) {
        synchronized (lifecycle) {
            boolean shouldRun = Config.enabled && allowedOnThisServer;
            if (!shouldRun) {
                stopLocked();
                return;
            }
            boolean restart;
            synchronized (this) {
                restart = server == null || !currentSettings().equals(runningSettings);
            }
            if (restart) {
                stopLocked();
                startLocked();
            }
        }
    }

    private static String currentSettings() {
        return Config.bindAddress + "|"
            + Config.port
            + "|"
            + Config.authToken
            + "|"
            + Config.maxClients
            + "|"
            + Config.maxMessageBytes;
    }

    void onStarted(BridgeServer s) {
        if (s == server) {
            listening = true;
            DaveBridge.LOG.info("Agent bridge listening on {}", s.getAddress());
        }
    }

    void onServerError(BridgeServer s, Exception ex) {
        lastError = ex.toString();
        DaveBridge.LOG.error(
            "Agent bridge socket failed ({}:{}): {}. Fix the config and run /dave reload.",
            Config.bindAddress,
            Config.port,
            ex.toString());
        synchronized (this) {
            if (s == server) {
                listening = false;
                server = null;
                runningSettings = null;
                // The library closes the connections itself but may never report onClose for them.
                sessions.clear();
            }
        }
    }

    // ---- sessions (socket threads) ----

    ClientSession newSession(WebSocket conn) {
        return new ClientSession(nextSessionId.incrementAndGet(), conn);
    }

    /**
     * A connection finished its handshake. {@code from} is the server that accepted it; connections of a server that
     * is already stopping are not tracked (the library closes them without ever reporting onClose).
     */
    void onOpen(BridgeServer from, ClientSession session, boolean preAuthenticated) {
        if (from != server || !session.isOpen()) {
            session.close(CloseFrame.GOING_AWAY, "server stopping");
            return;
        }
        sessions.add(session);
        DaveBridge.LOG.info("Agent connection {} opened", session);
        if (preAuthenticated) {
            authenticate(session);
            return;
        }
        ScheduledExecutorService timer = scheduler;
        if (timer != null) {
            session.authTimeout = timer.schedule(() -> {
                if (!session.isAuthenticated() && session.isOpen()) {
                    session.send(Protocol.error(Protocol.ERR_UNAUTHORIZED, "authentication timed out", null));
                    session.close(CloseFrame.POLICY_VALIDATION, "authentication timed out");
                }
            }, Config.authTimeoutSeconds, TimeUnit.SECONDS);
        }
    }

    void onMessage(ClientSession session, String raw) {
        JsonObject body;
        try {
            body = MessageRouter.parse(raw);
        } catch (ProtocolException e) {
            if (session.isAuthenticated()) {
                session.send(Protocol.error(e.code(), e.getMessage(), e.reqId()));
            } else {
                rejectUnauthenticated(session);
            }
            return;
        }
        String type = body.get("type")
            .getAsString();
        if (!session.isAuthenticated()) {
            String token = body.has("token") && body.get("token")
                .isJsonPrimitive() ? body.get("token")
                    .getAsString() : null;
            if ("auth".equals(type) && token != null && checkToken(token)) {
                authenticate(session);
            } else {
                rejectUnauthenticated(session);
            }
            return;
        }
        if ("auth".equals(type)) {
            session.send(Protocol.error(Protocol.ERR_BAD_REQUEST, "already authenticated", Protocol.reqIdOf(body)));
            return;
        }
        if (stopping) {
            session.send(Protocol.error(Protocol.ERR_CANCELLED, "server stopping", Protocol.reqIdOf(body)));
            return;
        }
        router.dispatch(session, body);
    }

    /** A binary frame: unsupported, and before authentication it counts as "anything else first". */
    void onBinaryMessage(ClientSession session) {
        if (session.isAuthenticated()) {
            session.send(Protocol.error(Protocol.ERR_BAD_REQUEST, "binary frames are not supported", null));
        } else {
            rejectUnauthenticated(session);
        }
    }

    /** PROTOCOL.md 1.1: anything but a valid auth first gets {@code unauthorized} and close code 1008. */
    private void rejectUnauthenticated(ClientSession session) {
        DaveBridge.LOG.warn("Agent connection {} failed to authenticate", session);
        session.send(Protocol.error(Protocol.ERR_UNAUTHORIZED, "send {\"type\":\"auth\",\"token\":...} first", null));
        session.close(CloseFrame.POLICY_VALIDATION, "unauthorized");
    }

    void onClose(ClientSession session, int code, String reason) {
        sessions.remove(session);
        DaveBridge.LOG.info("Agent connection {} closed ({} {})", session, code, reason);
    }

    private void authenticate(ClientSession session) {
        session.markAuthenticated();
        DaveBridge.LOG.info("Agent connection {} authenticated", session);
        JsonObject hello = Protocol.message("hello");
        hello.addProperty("protocol", Protocol.VERSION);
        hello.addProperty("mod", DaveBridge.MODID);
        hello.addProperty("version", Tags.VERSION);
        hello.addProperty("session", session.id());
        hello.addProperty("botName", Config.botName);
        JsonArray types = new JsonArray();
        for (String t : router.types()) {
            types.add(new JsonPrimitive(t));
        }
        hello.add("accepts", types);
        session.send(hello);
    }

    /** Constant-time comparison against the configured token. An empty configured token never matches. */
    public boolean checkToken(String candidate) {
        String expected = Config.authToken;
        if (expected == null || expected.isEmpty() || candidate == null) {
            return false;
        }
        return MessageDigest.isEqual(
            expected.getBytes(StandardCharsets.UTF_8),
            candidate.trim()
                .getBytes(StandardCharsets.UTF_8));
    }

    private void handlePing(Request request) {
        JsonObject pong = Protocol.message("pong");
        pong.addProperty("tick", serverTick);
        pong.addProperty("queueDepth", queue.depth());
        request.reply(pong);
    }

    // ---- outbound ----

    /** Sends {@code message} to every authenticated agent. Returns how many received it. Never throws. */
    public int broadcast(JsonObject message) {
        String text = message.toString();
        int sent = 0;
        for (ClientSession session : sessions) {
            if (session.isAuthenticated() && session.isOpen()) {
                try {
                    session.sendRaw(text);
                    sent++;
                } catch (Throwable t) {
                    DaveBridge.LOG.debug("Broadcast to {} failed", session, t);
                }
            }
        }
        return sent;
    }

    // ---- status ----

    public void setServerTick(int tick) {
        serverTick = tick;
    }

    public boolean isListening() {
        return listening;
    }

    public boolean isStarted() {
        return server != null;
    }

    public String lastError() {
        return lastError;
    }

    /** Drops sessions whose connection has closed without the library reporting it. */
    private void pruneClosed() {
        for (ClientSession session : sessions) {
            if (!session.isOpen()) {
                sessions.remove(session);
            }
        }
    }

    public int connectionCount() {
        pruneClosed();
        return sessions.size();
    }

    public int authenticatedCount() {
        pruneClosed();
        int n = 0;
        for (ClientSession session : sessions) {
            if (session.isAuthenticated()) {
                n++;
            }
        }
        return n;
    }

    public boolean hasAgent() {
        return authenticatedCount() > 0;
    }

    /** The open agent connections (read-only view). */
    public Set<ClientSession> sessions() {
        pruneClosed();
        return Collections.unmodifiableSet(sessions);
    }

    /** True while the server is stopping (or the bridge is stopped): new agent messages are cancelled. */
    public boolean isStopping() {
        return stopping;
    }
}
