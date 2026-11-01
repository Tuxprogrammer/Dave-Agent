package com.tuxprogrammer.davebridge.server.bridge;

import java.util.concurrent.ScheduledFuture;

import org.java_websocket.WebSocket;
import org.java_websocket.exceptions.WebsocketNotConnectedException;

import com.google.gson.JsonObject;

/** One WebSocket connection from an agent. Sending is thread-safe. */
public final class ClientSession {

    private final int id;
    private final WebSocket conn;
    private final String remote;
    private final long connectedAtMillis = System.currentTimeMillis();
    private volatile boolean authenticated;
    volatile ScheduledFuture<?> authTimeout;

    ClientSession(int id, WebSocket conn) {
        this.id = id;
        this.conn = conn;
        this.remote = String.valueOf(conn.getRemoteSocketAddress());
    }

    public int id() {
        return id;
    }

    public String remote() {
        return remote;
    }

    public long connectedAtMillis() {
        return connectedAtMillis;
    }

    public boolean isAuthenticated() {
        return authenticated;
    }

    void markAuthenticated() {
        authenticated = true;
        ScheduledFuture<?> timeout = authTimeout;
        if (timeout != null) {
            timeout.cancel(false);
        }
    }

    public boolean isOpen() {
        return conn.isOpen();
    }

    /** Sends a JSON message; silently drops it if the connection has closed meanwhile. */
    public void send(JsonObject message) {
        sendRaw(message.toString());
    }

    void sendRaw(String text) {
        try {
            if (conn.isOpen()) {
                conn.send(text);
            }
        } catch (WebsocketNotConnectedException ignored) {
            // closed between the check and the send
        }
    }

    public void close(int code, String reason) {
        conn.close(code, reason);
    }

    @Override
    public String toString() {
        return "agent#" + id + "@" + remote;
    }
}
