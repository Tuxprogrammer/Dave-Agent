package com.tuxprogrammer.davebridge.client;

import java.lang.ref.WeakReference;

/** What the client knows about the current server connection. Client thread only, except the volatile reads. */
public final class ClientState {

    /** Ask length used when the server did not say (older servers send no {@code maxAskLength}). */
    static final int DEFAULT_ASK_LENGTH = 1000;

    /** The connection we last said hello on; a new one means a new server (or a reconnect). */
    static WeakReference<Object> helloConnection = new WeakReference<>(null);

    /** Set when the server answered our hello with a compatible protocol, i.e. it runs DaveBridge. */
    public static volatile boolean serverHasMod;
    public static volatile String botName = "Dave";
    public static volatile String[] triggerPrefixes = new String[0];
    /** Longest question the server accepts, from {@code server_hello}. */
    public static volatile int maxAskLength = DEFAULT_ASK_LENGTH;
    /** Client ticks until the opt-in nudge shows; 0 means none is pending. Client thread only. */
    static int nudgeTicks;

    private ClientState() {}

    static void reset() {
        serverHasMod = false;
        botName = "Dave";
        triggerPrefixes = new String[0];
        maxAskLength = DEFAULT_ASK_LENGTH;
        nudgeTicks = 0;
    }

    /** The Ask line's length limit for a server-reported maximum (0 or less: the server did not say). */
    static int askLimit(int serverMax) {
        return serverMax > 0 ? serverMax : DEFAULT_ASK_LENGTH;
    }
}
