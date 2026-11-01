package com.tuxprogrammer.davebridge.server.eval;

import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * World-changing scripts waiting for the asking player's Confirm click. An accident guard, not security: it makes sure
 * a person saw what Dave is about to do before it happens.
 * <p>
 * Rules: only the player the confirm was shown to can confirm or cancel it; each token resolves once; it expires
 * after its time. No Minecraft types, so it is unit-tested directly. Thread-safe (all methods synchronized).
 */
public final class PendingConfirms<T> {

    public enum Outcome {
        /** The asker confirmed: run it. */
        CONFIRMED,
        /** The asker cancelled. */
        CANCELLED,
        /** Someone else clicked; nothing changes. */
        WRONG_PLAYER,
        /** No such token (already resolved, expired, or never existed). */
        UNKNOWN
    }

    public static final class Pending<T> {

        public final String token;
        public final UUID player;
        public final String playerName;
        public final long expiresAt;
        public final T payload;

        Pending(String token, UUID player, String playerName, long expiresAt, T payload) {
            this.token = token;
            this.player = player;
            this.playerName = playerName;
            this.expiresAt = expiresAt;
            this.payload = payload;
        }
    }

    public static final class Resolution<T> {

        public final Outcome outcome;
        /** The pending entry for CONFIRMED, CANCELLED and WRONG_PLAYER; null for UNKNOWN. */
        public final Pending<T> pending;

        Resolution(Outcome outcome, Pending<T> pending) {
            this.outcome = outcome;
            this.pending = pending;
        }
    }

    private final Map<String, Pending<T>> pending = new LinkedHashMap<>();
    private final SecureRandom random = new SecureRandom();
    private final int maxPerPlayer;

    public PendingConfirms(int maxPerPlayer) {
        this.maxPerPlayer = maxPerPlayer;
    }

    /** Adds a confirm, or returns null if the player already has {@code maxPerPlayer} waiting. */
    public synchronized Pending<T> create(UUID player, String playerName, long now, long ttlMillis, T payload) {
        if (countFor(player) >= maxPerPlayer) {
            return null;
        }
        String token;
        do {
            token = Long.toHexString(random.nextLong() & 0xffffffffffL);
        } while (pending.containsKey(token));
        Pending<T> p = new Pending<>(token, player, playerName, now + ttlMillis, payload);
        pending.put(token, p);
        return p;
    }

    /**
     * A click on Confirm ({@code confirm}) or Cancel by player {@code by}, or by the server console when {@code by} is
     * null (the console, an op's test tool, may answer any confirm). An expired token is UNKNOWN.
     */
    public synchronized Resolution<T> resolve(String token, UUID by, boolean confirm, long now) {
        Pending<T> p = token == null ? null : pending.get(token.trim());
        if (p == null || now > p.expiresAt) {
            return new Resolution<>(Outcome.UNKNOWN, null);
        }
        if (by != null && !p.player.equals(by)) {
            return new Resolution<>(Outcome.WRONG_PLAYER, p);
        }
        pending.remove(p.token);
        return new Resolution<>(confirm ? Outcome.CONFIRMED : Outcome.CANCELLED, p);
    }

    /** Removes and returns every entry past its time. */
    public synchronized List<Pending<T>> expire(long now) {
        List<Pending<T>> out = new ArrayList<>();
        for (Iterator<Pending<T>> it = pending.values()
            .iterator(); it.hasNext();) {
            Pending<T> p = it.next();
            if (now > p.expiresAt) {
                it.remove();
                out.add(p);
            }
        }
        return out;
    }

    /** Removes and returns everything (server stopping). */
    public synchronized List<Pending<T>> clear() {
        List<Pending<T>> out = new ArrayList<>(pending.values());
        pending.clear();
        return out;
    }

    /** A snapshot of everything waiting, oldest first. */
    public synchronized List<Pending<T>> list() {
        return new ArrayList<>(pending.values());
    }

    public synchronized int countFor(UUID player) {
        int n = 0;
        for (Pending<T> p : pending.values()) {
            if (p.player.equals(player)) {
                n++;
            }
        }
        return n;
    }

    public synchronized int size() {
        return pending.size();
    }
}
