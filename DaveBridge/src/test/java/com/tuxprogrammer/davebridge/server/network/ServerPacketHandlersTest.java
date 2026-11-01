package com.tuxprogrammer.davebridge.server.network;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.tuxprogrammer.davebridge.common.protocol.DavePackets;
import com.tuxprogrammer.davebridge.server.ClientModTracker;

class ServerPacketHandlersTest {

    private static final String[] PREFIXES = { "dave,", "@dave" };

    @Test
    void acceptsQuestionAndStripsPrefixFromPromptOnly() {
        ServerPacketHandlers.AskCheck c = ServerPacketHandlers.checkAsk("  dave, what is steel?  ", 100, PREFIXES);
        assertNull(c.error);
        assertEquals("dave, what is steel?", c.text);
        assertEquals("what is steel?", c.prompt);
    }

    @Test
    void questionWithoutPrefixIsItsOwnPrompt() {
        ServerPacketHandlers.AskCheck c = ServerPacketHandlers.checkAsk("where is titanium", 100, PREFIXES);
        assertNull(c.error);
        assertEquals("where is titanium", c.prompt);
    }

    @Test
    void rejectsEmptyAndMissingText() {
        assertNotNull(ServerPacketHandlers.checkAsk("   ", 100, PREFIXES).error);
        assertNotNull(ServerPacketHandlers.checkAsk(null, 100, PREFIXES).error);
    }

    @Test
    void rejectsPrefixWithoutQuestion() {
        // What the Ask key's prefilled "dave, " becomes when Enter is pressed straight away.
        ServerPacketHandlers.AskCheck c = ServerPacketHandlers.checkAsk("dave,", 100, PREFIXES);
        assertNotNull(c.error);
        assertNull(c.prompt);
    }

    @Test
    void rejectsTooLongWithBothLengthsInTheMessage() {
        ServerPacketHandlers.AskCheck c = ServerPacketHandlers.checkAsk("abcdefghijk", 10, PREFIXES);
        assertNotNull(c.error);
        assertTrue(c.error.contains("11"), c.error);
        assertTrue(c.error.contains("10"), c.error);
        assertNull(ServerPacketHandlers.checkAsk("abcdefghij", 10, PREFIXES).error);
    }

    @Test
    void modLinksNeedNeiCapabilityAndSameProtocol() {
        ClientModTracker tracker = new ClientModTracker();
        int protocol = DavePackets.PROTOCOL_VERSION;
        assertFalse(ServerPacketHandlers.supportsModLinks(null));
        assertTrue(
            ServerPacketHandlers.supportsModLinks(
                tracker.put(UUID.randomUUID(), "1", protocol, new String[] { "render", "nei" }, false)));
        assertFalse(
            ServerPacketHandlers.supportsModLinks(
                tracker.put(UUID.randomUUID(), "1", protocol, new String[] { "render", "ask", "context" }, false)));
        assertFalse(
            ServerPacketHandlers
                .supportsModLinks(tracker.put(UUID.randomUUID(), "1", protocol + 1, new String[] { "nei" }, false)));
        assertFalse(ServerPacketHandlers.supportsModLinks(tracker.put(UUID.randomUUID(), "1", protocol, null, false)));
    }
}
