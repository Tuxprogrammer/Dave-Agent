package com.tuxprogrammer.davebridge.server.compat;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.Test;

class BqQuestsTest {

    /** A fake quest database. */
    private static BqQuests.Source source(final Map<UUID, String> quests) {
        return new BqQuests.Source() {

            @Override
            public String nameOf(UUID id) {
                return quests.get(id);
            }

            @Override
            public Iterable<UUID> ids() {
                return quests.keySet();
            }
        };
    }

    @Test
    void idsAndNamesResolve() {
        Map<UUID, String> quests = new LinkedHashMap<>();
        UUID steel = new UUID(0, 106);
        quests.put(steel, "Steel");
        BqQuests.Source src = source(quests);
        assertEquals(steel, BqQuests.find(BqQuests.encode(steel), src).id);
        assertEquals(steel, BqQuests.find(steel.toString(), src).id);
        assertEquals(steel, BqQuests.find(" steel ", src).id);
        assertNull(BqQuests.find("Iron", src));
    }

    @Test
    void aNameThatLooksLikeACompactIdIsStillFoundByName() {
        String name = "ThaumcraftIntroduction"; // 22 base64-safe characters
        assertEquals(22, name.length());
        assertNotNull(BqQuests.parseId(name));
        Map<UUID, String> quests = new LinkedHashMap<>();
        UUID id = UUID.randomUUID();
        quests.put(id, name);
        BqQuests.Quest q = BqQuests.find(name, source(quests));
        assertNotNull(q);
        assertEquals(id, q.id);
        assertEquals(1, q.matches);
    }
}
