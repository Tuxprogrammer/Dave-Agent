package com.tuxprogrammer.davebridge.common.protocol;

import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/** Registry of packet kinds and the direction each may travel. */
public final class DavePackets {

    /** Bumped on incompatible changes to the packet channel. */
    public static final int PROTOCOL_VERSION = 1;

    public enum Direction {
        TO_SERVER,
        TO_CLIENT
    }

    private static final Map<String, Class<? extends DavePacket>> TYPES = new HashMap<>();
    private static final Map<String, Direction> DIRECTIONS = new HashMap<>();

    static {
        register(ClientHello.KIND, ClientHello.class, Direction.TO_SERVER);
        register(Ask.KIND, Ask.class, Direction.TO_SERVER);
        register(ClientEvalResult.KIND, ClientEvalResult.class, Direction.TO_SERVER);
        register(ClientSettings.KIND, ClientSettings.class, Direction.TO_SERVER);
        register(ServerHello.KIND, ServerHello.class, Direction.TO_CLIENT);
        register(DaveMessage.KIND, DaveMessage.class, Direction.TO_CLIENT);
        register(Thinking.KIND, Thinking.class, Direction.TO_CLIENT);
        register(ClientEvalRequest.KIND, ClientEvalRequest.class, Direction.TO_CLIENT);
    }

    private DavePackets() {}

    private static void register(String kind, Class<? extends DavePacket> type, Direction direction) {
        TYPES.put(kind, type);
        DIRECTIONS.put(kind, direction);
    }

    /** The packet class for {@code kind}, or null if unknown. */
    public static Class<? extends DavePacket> type(String kind) {
        return TYPES.get(kind);
    }

    public static Direction direction(String kind) {
        return DIRECTIONS.get(kind);
    }

    public static Map<String, Class<? extends DavePacket>> all() {
        return Collections.unmodifiableMap(TYPES);
    }
}
