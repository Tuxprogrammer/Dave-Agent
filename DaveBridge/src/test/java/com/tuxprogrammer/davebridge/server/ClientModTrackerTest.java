package com.tuxprogrammer.davebridge.server;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.UUID;

import org.junit.jupiter.api.Test;

class ClientModTrackerTest {

    private final UUID steve = UUID.randomUUID();

    @Test
    void optInChangeUpdatesTheRecord() {
        ClientModTracker tracker = new ClientModTracker();
        tracker.put(steve, "0.1.2", 1, new String[] { "render" }, false);
        ClientModTracker.Info info = tracker.setClientEvalAllowed(steve, true);
        assertTrue(info.clientEvalAllowed);
        assertTrue(tracker.get(steve).clientEvalAllowed);
    }

    @Test
    void unchangedOptInIsNotReannounced() {
        ClientModTracker tracker = new ClientModTracker();
        tracker.put(steve, "0.1.2", 1, new String[0], true);
        assertNull(tracker.setClientEvalAllowed(steve, true));
    }

    @Test
    void optInWithoutHelloIsIgnored() {
        ClientModTracker tracker = new ClientModTracker();
        assertNull(tracker.setClientEvalAllowed(steve, true));
        assertFalse(tracker.hasClientMod(steve));
    }

    @Test
    void optInChangeKeepsTheAskCooldown() {
        ClientModTracker tracker = new ClientModTracker();
        tracker.put(steve, "0.1.2", 1, new String[0], false);
        assertTrue(tracker.tryAsk(steve, 10_000L, 1_000L));
        tracker.setClientEvalAllowed(steve, true);
        assertFalse(tracker.tryAsk(steve, 10_500L, 1_000L));
    }
}
