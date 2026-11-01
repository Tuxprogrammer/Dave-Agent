package com.tuxprogrammer.davebridge.client;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** ClientState has no Minecraft references, so its pure parts are testable without a client. */
class ClientStateTest {

    @Test
    void askLimitFollowsTheServer() {
        assertEquals(500, ClientState.askLimit(500));
        assertEquals(2000, ClientState.askLimit(2000));
    }

    @Test
    void askLimitFallsBackForServersThatDoNotSay() {
        assertEquals(ClientState.DEFAULT_ASK_LENGTH, ClientState.askLimit(0));
        assertEquals(ClientState.DEFAULT_ASK_LENGTH, ClientState.askLimit(-1));
    }

    @Test
    void resetRestoresTheDefaultLimit() {
        ClientState.maxAskLength = 42;
        ClientState.reset();
        assertEquals(ClientState.DEFAULT_ASK_LENGTH, ClientState.maxAskLength);
    }
}
