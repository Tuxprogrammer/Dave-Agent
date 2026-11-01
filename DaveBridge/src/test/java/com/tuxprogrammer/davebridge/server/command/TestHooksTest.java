package com.tuxprogrammer.davebridge.server.command;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.util.UUID;

import org.junit.jupiter.api.Test;

class TestHooksTest {

    @Test
    void parsesNamePositionAndQuestion() {
        TestHooks.Ask a = TestHooks
            .parseAsk(new String[] { "ask", "Gym", "@10,64.5,-3,7", "where", "is", "my", "EBF?" }, 1);
        assertEquals("Gym", a.name);
        assertArrayEquals(new double[] { 10, 64.5, -3 }, a.pos);
        assertEquals(Integer.valueOf(7), a.dim);
        assertEquals("where is my EBF?", a.question);

        TestHooks.Ask b = TestHooks.parseAsk(new String[] { "ask", "Gym", "@1,2,3", "hi" }, 1);
        assertNull(b.dim);
        TestHooks.Ask c = TestHooks.parseAsk(new String[] { "ask", "Gym", "dave,", "steel?" }, 1);
        assertNull(c.pos);
        assertEquals("dave, steel?", c.question);

        assertNull(TestHooks.parseAsk(new String[] { "ask", "Gym" }, 1));
        assertNull(TestHooks.parseAsk(new String[] { "ask", "Gym", "@1,2,3" }, 1), "position but no question");
    }

    @Test
    void offlineUuidMatchesVanillaOfflineMode() {
        // vanilla: UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes(UTF_8))
        assertEquals(
            UUID.nameUUIDFromBytes("OfflinePlayer:Gym".getBytes(java.nio.charset.StandardCharsets.UTF_8)),
            TestHooks.offlineUuid("Gym"));
        assertEquals(
            3,
            TestHooks.offlineUuid("Gym")
                .version());
        assertEquals(TestHooks.offlineUuid("Gym"), TestHooks.offlineUuid("Gym"));
    }
}
