package com.tuxprogrammer.davebridge.server.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import com.google.gson.JsonObject;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.common.tasks.MainThreadQueue;

/** Auth, error codes, reqId echo and shutdown behavior of the agent protocol, driven without a socket. */
class BridgeServiceTest {

    private static final String TOKEN = "unit-test-token";
    private static final int POLICY_VIOLATION = 1008;

    private String savedToken;
    private MainThreadQueue queue;
    private BridgeService service;

    @BeforeEach
    void setUp() {
        savedToken = Config.authToken;
        Config.authToken = TOKEN;
        queue = new MainThreadQueue();
        service = new BridgeService(queue);
        service.router()
            .register(
                "work",
                request -> service.router()
                    .runOnMainThread(request, "work", () -> null));
        service.router()
            .register(
                "boom",
                request -> service.router()
                    .runOnMainThread(request, "boom", () -> { throw new IllegalStateException("kaput"); }));
        service.router()
            .register("refuse", request -> { throw new ProtocolException(Protocol.ERR_NOT_FOUND, "nobody here"); });
    }

    @AfterEach
    void tearDown() {
        Config.authToken = savedToken;
    }

    /** Opens a connection without authenticating it. */
    private ClientSession connect(FakeConnection c) {
        ClientSession s = service.newSession(c.socket);
        service.onOpen(null, s, false);
        assertEquals(1, service.connectionCount());
        return s;
    }

    /** Opens a connection and authenticates it with the auth message. */
    private ClientSession authenticated(FakeConnection c) {
        ClientSession s = connect(c);
        service.onMessage(s, "{\"type\":\"auth\",\"token\":\"" + TOKEN + "\"}");
        assertEquals("hello", type(c.last()));
        assertTrue(s.isAuthenticated());
        c.sent.clear();
        return s;
    }

    private static String type(JsonObject msg) {
        return msg.get("type")
            .getAsString();
    }

    private static void assertError(JsonObject msg, String code, Integer reqId) {
        assertNotNull(msg, "expected an error");
        assertEquals("error", type(msg));
        assertEquals(
            code,
            msg.get("code")
                .getAsString());
        if (reqId == null) {
            assertNull(msg.get("reqId"));
        } else {
            assertEquals(
                reqId.intValue(),
                msg.get("reqId")
                    .getAsInt());
        }
    }

    private static void assertRejected(FakeConnection c) {
        assertError(c.last(), Protocol.ERR_UNAUTHORIZED, null);
        assertFalse(c.open);
        assertEquals(POLICY_VIOLATION, c.closeCode);
    }

    // ---- authentication ----

    @Test
    void correctTokenGetsHello() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        assertTrue(c.open);
        assertEquals(1, service.authenticatedCount());
        assertTrue(s.isAuthenticated());
    }

    @Test
    void wrongTokenIsRejected() {
        FakeConnection c = new FakeConnection();
        service.onMessage(connect(c), "{\"type\":\"auth\",\"token\":\"nope\"}");
        assertRejected(c);
    }

    @Test
    void otherMessageFirstIsRejected() {
        FakeConnection c = new FakeConnection();
        service.onMessage(connect(c), "{\"type\":\"ping\",\"reqId\":1}");
        assertRejected(c);
    }

    @Test
    void malformedJsonFirstIsUnauthorized() {
        FakeConnection c = new FakeConnection();
        service.onMessage(connect(c), "{not json");
        assertRejected(c);
    }

    @Test
    void missingTypeFirstIsUnauthorized() {
        FakeConnection c = new FakeConnection();
        service.onMessage(connect(c), "{\"token\":\"" + TOKEN + "\"}");
        assertRejected(c);
    }

    @Test
    void binaryFrameFirstIsUnauthorized() {
        FakeConnection c = new FakeConnection();
        service.onBinaryMessage(connect(c));
        assertRejected(c);
    }

    @Test
    void emptyConfiguredTokenNeverMatches() {
        Config.authToken = "";
        assertFalse(service.checkToken(""));
        Config.authToken = TOKEN;
        assertTrue(service.checkToken(" " + TOKEN + " "));
        assertFalse(service.checkToken(TOKEN + "x"));
    }

    // ---- errors after authentication ----

    @Test
    void missingTypeIsBadJsonWithReqId() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onMessage(s, "{\"reqId\":7}");
        assertError(c.last(), Protocol.ERR_BAD_JSON, 7);
        service.onMessage(s, "{\"type\":5,\"reqId\":8}");
        assertError(c.last(), Protocol.ERR_BAD_JSON, 8);
        assertTrue(c.open, "errors never close an authenticated connection");
    }

    @Test
    void malformedJsonIsBadJson() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onMessage(s, "[1,2]");
        assertError(c.last(), Protocol.ERR_BAD_JSON, null);
        service.onMessage(s, "{\"type\":");
        assertError(c.last(), Protocol.ERR_BAD_JSON, null);
        assertTrue(c.open);
    }

    @Test
    void unknownTypeEchoesReqId() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onMessage(s, "{\"type\":\"nope\",\"reqId\":3}");
        assertError(c.last(), Protocol.ERR_UNKNOWN_TYPE, 3);
    }

    @Test
    void secondAuthIsBadRequest() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onMessage(s, "{\"type\":\"auth\",\"token\":\"" + TOKEN + "\",\"reqId\":4}");
        assertError(c.last(), Protocol.ERR_BAD_REQUEST, 4);
        assertTrue(c.open);
    }

    @Test
    void binaryFrameAfterAuthIsBadRequest() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onBinaryMessage(s);
        assertError(c.last(), Protocol.ERR_BAD_REQUEST, null);
        assertTrue(c.open);
    }

    @Test
    void handlerProtocolExceptionKeepsItsCode() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onMessage(s, "{\"type\":\"refuse\",\"reqId\":5}");
        assertError(c.last(), Protocol.ERR_NOT_FOUND, 5);
    }

    @Test
    void pingAnswersImmediately() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onMessage(s, "{\"type\":\"ping\",\"reqId\":\"p\"}");
        assertEquals("pong", type(c.last()));
        assertEquals(
            "p",
            c.last()
                .get("reqId")
                .getAsString());
    }

    // ---- main-thread work ----

    @Test
    void queuedWorkAcksAfterDrain() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onMessage(s, "{\"type\":\"work\",\"reqId\":10}");
        assertTrue(c.sent.isEmpty(), "reply comes on the tick, not immediately");
        queue.drain(Long.MAX_VALUE);
        assertEquals("ack", type(c.last()));
        assertEquals(
            10,
            c.last()
                .get("reqId")
                .getAsInt());
    }

    @Test
    void failingWorkIsInternal() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onMessage(s, "{\"type\":\"boom\",\"reqId\":11}");
        queue.drain(Long.MAX_VALUE);
        assertError(c.last(), Protocol.ERR_INTERNAL, 11);
    }

    @Test
    void fullQueueIsQueueFull() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        queue.setMaxDepth(1);
        queue.submit("filler", () -> {});
        service.onMessage(s, "{\"type\":\"work\",\"reqId\":12}");
        assertError(c.last(), Protocol.ERR_QUEUE_FULL, 12);
    }

    // ---- shutdown ----

    @Test
    void queuedWorkIsCancelledWhileTheSocketIsStillOpen() {
        FakeConnection c = new FakeConnection();
        ClientSession s = authenticated(c);
        service.onMessage(s, "{\"type\":\"work\",\"reqId\":20}");
        // DaveServer's shutdown order: refuse new messages, clear the queue, then close the sockets.
        service.beginStopping();
        queue.clear("server stopping");
        assertError(c.last(), Protocol.ERR_CANCELLED, 20);
        service.onMessage(s, "{\"type\":\"work\",\"reqId\":21}");
        assertError(c.last(), Protocol.ERR_CANCELLED, 21);
        assertEquals(0, queue.depth(), "nothing is queued once stopping");
    }

    // ---- session bookkeeping ----

    @Test
    void closedConnectionsAreNotCounted() {
        FakeConnection c = new FakeConnection();
        authenticated(c);
        assertEquals(1, service.connectionCount());
        c.open = false; // closed without the library reporting onClose
        assertEquals(0, service.connectionCount());
        assertEquals(0, service.authenticatedCount());
        assertTrue(
            service.sessions()
                .isEmpty());
    }

    @Test
    void connectionOfAStoppedServerIsNotTracked() {
        FakeConnection c = new FakeConnection();
        c.open = false; // the library closes connections that arrive while it stops, then still calls onOpen
        service.onOpen(null, service.newSession(c.socket), true);
        assertEquals(0, service.connectionCount());
        assertTrue(c.sent.isEmpty(), "no hello for a connection that is going away");
    }
}
