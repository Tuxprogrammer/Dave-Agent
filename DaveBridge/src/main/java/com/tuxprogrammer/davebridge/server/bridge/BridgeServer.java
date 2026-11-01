package com.tuxprogrammer.davebridge.server.bridge;

import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.util.Collections;

import org.java_websocket.WebSocket;
import org.java_websocket.drafts.Draft;
import org.java_websocket.drafts.Draft_6455;
import org.java_websocket.exceptions.InvalidDataException;
import org.java_websocket.extensions.IExtension;
import org.java_websocket.framing.CloseFrame;
import org.java_websocket.handshake.ClientHandshake;
import org.java_websocket.handshake.ServerHandshakeBuilder;
import org.java_websocket.server.WebSocketServer;

import com.tuxprogrammer.davebridge.DaveBridge;

/**
 * The Java-WebSocket server. Thin: connection bookkeeping and header auth here, everything else in
 * {@link BridgeService}. All callbacks are wrapped so nothing propagates into the library's threads.
 */
final class BridgeServer extends WebSocketServer {

    /** Attachment marking a connection that authenticated with a header during the handshake. */
    private static final Object PRE_AUTHENTICATED = new Object();

    private final BridgeService service;
    private final int maxClients;

    BridgeServer(InetSocketAddress address, BridgeService service, int maxClients, int maxFrameBytes) {
        super(
            address,
            Collections.<Draft>singletonList(new Draft_6455(Collections.<IExtension>emptyList(), maxFrameBytes)));
        this.service = service;
        this.maxClients = maxClients;
        setReuseAddr(true);
        setDaemon(true);
        setTcpNoDelay(true);
        setConnectionLostTimeout(30);
    }

    @Override
    public ServerHandshakeBuilder onWebsocketHandshakeReceivedAsServer(WebSocket conn, Draft draft,
        ClientHandshake request) throws InvalidDataException {
        ServerHandshakeBuilder builder = super.onWebsocketHandshakeReceivedAsServer(conn, draft, request);
        if (getConnections().size() >= maxClients) {
            throw new InvalidDataException(CloseFrame.TRY_AGAIN_LATER, "too many connections");
        }
        String token = headerToken(request);
        if (token != null) {
            if (!service.checkToken(token)) {
                DaveBridge.LOG
                    .warn("Rejected WebSocket handshake with a bad token from {}", conn.getRemoteSocketAddress());
                throw new InvalidDataException(CloseFrame.POLICY_VALIDATION, "bad token");
            }
            conn.setAttachment(PRE_AUTHENTICATED);
        }
        return builder;
    }

    /** {@code Authorization: Bearer <token>} or {@code X-Dave-Token: <token>}, or null. */
    private static String headerToken(ClientHandshake request) {
        String auth = request.getFieldValue("Authorization");
        if (auth != null && auth.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return auth.substring(7)
                .trim();
        }
        String token = request.getFieldValue("X-Dave-Token");
        return token == null || token.isEmpty() ? null : token.trim();
    }

    @Override
    public void onOpen(WebSocket conn, ClientHandshake handshake) {
        try {
            boolean preAuthenticated = conn.getAttachment() == PRE_AUTHENTICATED;
            ClientSession session = service.newSession(conn);
            conn.setAttachment(session);
            service.onOpen(this, session, preAuthenticated);
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Error opening WebSocket session", t);
            conn.close(CloseFrame.UNEXPECTED_CONDITION, "internal error");
        }
    }

    @Override
    public void onMessage(WebSocket conn, String message) {
        try {
            Object attachment = conn.getAttachment();
            if (attachment instanceof ClientSession) {
                service.onMessage((ClientSession) attachment, message);
            }
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Error handling WebSocket message", t);
        }
    }

    @Override
    public void onMessage(WebSocket conn, ByteBuffer message) {
        try {
            Object attachment = conn.getAttachment();
            if (attachment instanceof ClientSession) {
                service.onBinaryMessage((ClientSession) attachment);
            }
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Error handling binary WebSocket message", t);
        }
    }

    @Override
    public void onClose(WebSocket conn, int code, String reason, boolean remote) {
        try {
            Object attachment = conn.getAttachment();
            if (attachment instanceof ClientSession) {
                service.onClose((ClientSession) attachment, code, reason);
            }
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Error closing WebSocket session", t);
        }
    }

    @Override
    public void onError(WebSocket conn, Exception ex) {
        try {
            if (conn == null) {
                service.onServerError(this, ex); // bind failure or the selector died
            } else {
                DaveBridge.LOG.debug("WebSocket error on {}", conn.getRemoteSocketAddress(), ex);
            }
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Error handling WebSocket error", t);
        }
    }

    @Override
    public void onStart() {
        service.onStarted(this);
    }
}
