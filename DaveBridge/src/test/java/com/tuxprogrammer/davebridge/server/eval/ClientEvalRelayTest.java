package com.tuxprogrammer.davebridge.server.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.tuxprogrammer.davebridge.common.protocol.DavePackets;
import com.tuxprogrammer.davebridge.server.ClientModTracker;

/** Client eval goes only to players who opted in, with a client half that can run it; the latest opt-in counts. */
class ClientEvalRelayTest {

    private static final String[] CAPS = { "render", "ask", "context", "eval" };

    @Test
    void onlyOptedInClientsWithTheEvalCapability() {
        ClientModTracker tracker = new ClientModTracker();
        UUID steve = UUID.randomUUID();
        assertEquals("not_opted_in", ClientEvalRelay.gate(tracker.get(steve)), "no client half at all");

        tracker.put(steve, "0.2.0", DavePackets.PROTOCOL_VERSION, CAPS, false);
        assertEquals("not_opted_in", ClientEvalRelay.gate(tracker.get(steve)), "default: not opted in");

        tracker.setClientEvalAllowed(steve, true);
        assertNull(ClientEvalRelay.gate(tracker.get(steve)), "opted in mid-session");

        tracker.setClientEvalAllowed(steve, false);
        assertEquals("not_opted_in", ClientEvalRelay.gate(tracker.get(steve)), "opting out is respected at once");

        UUID old = UUID.randomUUID();
        tracker.put(old, "0.1.2", DavePackets.PROTOCOL_VERSION, new String[] { "render", "ask" }, true);
        assertEquals("unsupported", ClientEvalRelay.gate(tracker.get(old)), "an old client half cannot run scripts");

        UUID other = UUID.randomUUID();
        tracker.put(other, "9.9.9", DavePackets.PROTOCOL_VERSION + 1, CAPS, true);
        assertEquals("not_opted_in", ClientEvalRelay.gate(tracker.get(other)), "a different packet protocol");
    }
}
