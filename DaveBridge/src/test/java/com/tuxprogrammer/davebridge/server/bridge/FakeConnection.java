package com.tuxprogrammer.davebridge.server.bridge;

import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;

import org.java_websocket.WebSocket;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

/** A {@link WebSocket} stand-in that records what the server sends and how it closes. No socket involved. */
final class FakeConnection {

    final List<JsonObject> sent = new ArrayList<>();
    boolean open = true;
    int closeCode = -1;
    final WebSocket socket;

    FakeConnection() {
        socket = (WebSocket) Proxy.newProxyInstance(
            WebSocket.class.getClassLoader(),
            new Class<?>[] { WebSocket.class },
            (proxy, method, args) -> {
                switch (method.getName()) {
                    case "isOpen":
                        return open;
                    case "send":
                        if (args != null && args.length == 1 && args[0] instanceof String) {
                            sent.add(
                                new JsonParser().parse((String) args[0])
                                    .getAsJsonObject());
                        }
                        return null;
                    case "close":
                        if (open && args != null && args.length >= 1 && args[0] instanceof Integer) {
                            closeCode = (Integer) args[0];
                        }
                        open = false;
                        return null;
                    case "hashCode":
                        return System.identityHashCode(proxy);
                    case "equals":
                        return proxy == args[0];
                    case "toString":
                        return "FakeConnection";
                    default:
                        Class<?> type = method.getReturnType();
                        if (type == boolean.class) {
                            return false;
                        }
                        if (type == int.class) {
                            return 0;
                        }
                        if (type == long.class) {
                            return 0L;
                        }
                        return null;
                }
            });
    }

    JsonObject last() {
        return sent.isEmpty() ? null : sent.get(sent.size() - 1);
    }
}
