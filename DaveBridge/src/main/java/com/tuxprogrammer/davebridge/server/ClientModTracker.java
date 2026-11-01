package com.tuxprogrammer.davebridge.server;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/** Thread-safe record of which online players run the DaveBridge client half. */
public final class ClientModTracker {

    /** What a client reported in its hello. Immutable. */
    public static final class Info {

        public final String modVersion;
        public final int protocol;
        public final String[] capabilities;
        public final boolean clientEvalAllowed;
        /** Shared with copies made by {@link #withClientEvalAllowed}, so an opt-in change keeps the ask cooldown. */
        final long[] lastAskMillis;

        Info(String modVersion, int protocol, String[] capabilities, boolean clientEvalAllowed) {
            this(modVersion, protocol, capabilities, clientEvalAllowed, new long[] { 0L });
        }

        private Info(String modVersion, int protocol, String[] capabilities, boolean clientEvalAllowed,
            long[] lastAskMillis) {
            this.modVersion = modVersion;
            this.protocol = protocol;
            this.capabilities = capabilities;
            this.clientEvalAllowed = clientEvalAllowed;
            this.lastAskMillis = lastAskMillis;
        }

        private Info withClientEvalAllowed(boolean allowed) {
            return new Info(modVersion, protocol, capabilities, allowed, lastAskMillis);
        }
    }

    private final Map<UUID, Info> players = new ConcurrentHashMap<>();

    public Info put(UUID player, String modVersion, int protocol, String[] capabilities, boolean clientEvalAllowed) {
        Info info = new Info(modVersion, protocol, capabilities, clientEvalAllowed);
        players.put(player, info);
        return info;
    }

    /**
     * Records a mid-session opt-in change. Returns the updated info, or null if the player has no client half or the
     * value did not change (so repeats are not re-announced to the agent).
     */
    public Info setClientEvalAllowed(UUID player, boolean allowed) {
        Info[] changed = { null };
        players.computeIfPresent(player, (id, info) -> {
            if (info.clientEvalAllowed == allowed) {
                return info;
            }
            changed[0] = info.withClientEvalAllowed(allowed);
            return changed[0];
        });
        return changed[0];
    }

    public Info get(UUID player) {
        return players.get(player);
    }

    public boolean hasClientMod(UUID player) {
        return players.containsKey(player);
    }

    public void remove(UUID player) {
        players.remove(player);
    }

    public void clear() {
        players.clear();
    }

    public int count() {
        return players.size();
    }

    /**
     * Rate limit for Ask packets: true (and the clock is reset) if at least {@code cooldownMillis} passed since the
     * player's last accepted ask.
     */
    public boolean tryAsk(UUID player, long nowMillis, long cooldownMillis) {
        Info info = players.get(player);
        if (info == null) {
            return false;
        }
        synchronized (info.lastAskMillis) {
            if (nowMillis - info.lastAskMillis[0] < cooldownMillis) {
                return false;
            }
            info.lastAskMillis[0] = nowMillis;
            return true;
        }
    }
}
