package com.tuxprogrammer.davebridge.server.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;

import java.util.UUID;

import org.junit.jupiter.api.Test;

/** The confirm flow for world-changing scripts: who may click, once only, and expiry. */
class PendingConfirmsTest {

    private final UUID steve = UUID.randomUUID();
    private final UUID alex = UUID.randomUUID();

    @Test
    void onlyTheAskedPlayerConfirmsAndOnlyOnce() {
        PendingConfirms<String> c = new PendingConfirms<>(5);
        PendingConfirms.Pending<String> p = c.create(steve, "Steve", 1000, 60_000, "job");
        assertEquals(
            PendingConfirms.Outcome.WRONG_PLAYER,
            c.resolve(p.token, alex, true, 2000).outcome,
            "someone else's click does nothing");
        PendingConfirms.Resolution<String> ok = c.resolve(p.token, steve, true, 2000);
        assertEquals(PendingConfirms.Outcome.CONFIRMED, ok.outcome);
        assertSame("job", ok.pending.payload);
        assertEquals(PendingConfirms.Outcome.UNKNOWN, c.resolve(p.token, steve, true, 2000).outcome, "no double run");
    }

    @Test
    void cancelAndExpiry() {
        PendingConfirms<String> c = new PendingConfirms<>(5);
        PendingConfirms.Pending<String> a = c.create(steve, "Steve", 0, 1000, "a");
        PendingConfirms.Pending<String> b = c.create(steve, "Steve", 0, 5000, "b");
        assertEquals(PendingConfirms.Outcome.CANCELLED, c.resolve(a.token, steve, false, 10).outcome);
        assertEquals(PendingConfirms.Outcome.UNKNOWN, c.resolve(b.token, steve, true, 6000).outcome, "expired");
        assertEquals(
            1,
            c.expire(6000)
                .size());
        assertEquals(0, c.size());
    }

    @Test
    void theConsoleMayAnswerAnyConfirm() {
        PendingConfirms<String> c = new PendingConfirms<>(5);
        PendingConfirms.Pending<String> p = c.create(steve, "Steve", 0, 1000, "job");
        assertEquals(
            1,
            c.list()
                .size());
        assertEquals(PendingConfirms.Outcome.CONFIRMED, c.resolve(p.token, null, true, 10).outcome);
        assertEquals(0, c.size());
    }

    @Test
    void capPerPlayer() {
        PendingConfirms<String> c = new PendingConfirms<>(2);
        assertNotNull(c.create(steve, "Steve", 0, 1000, "1"));
        assertNotNull(c.create(steve, "Steve", 0, 1000, "2"));
        assertNull(c.create(steve, "Steve", 0, 1000, "3"));
        assertNotNull(c.create(alex, "Alex", 0, 1000, "4"));
        assertEquals(PendingConfirms.Outcome.UNKNOWN, c.resolve(null, steve, true, 0).outcome);
    }
}
