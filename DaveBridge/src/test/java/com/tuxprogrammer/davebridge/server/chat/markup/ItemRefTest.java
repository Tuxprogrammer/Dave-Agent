package com.tuxprogrammer.davebridge.server.chat.markup;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

class ItemRefTest {

    @Test
    void forms() {
        ItemRef r = ItemRef.parse("gregtech:gt.metaitem.01:11305");
        assertEquals("gregtech:gt.metaitem.01", r.name);
        assertEquals(11305, r.meta);
        assertEquals(1, r.count);

        assertEquals(3, ItemRef.parse("minecraft:wool@3").meta);
        assertEquals("minecraft:iron_ingot", ItemRef.parse("iron_ingot").name);
        assertEquals("ingotSteel", ItemRef.parse("ore:ingotSteel").ore);
        ItemRef n = ItemRef.parse("265:2");
        assertEquals(265, n.numericId);
        assertEquals(2, n.meta);
        ItemRef c = ItemRef.parse(" minecraft:iron_ingot*16 ");
        assertEquals(16, c.count);
        assertEquals("minecraft:iron_ingot", c.name);
    }

    @Test
    void malformed() {
        assertNull(ItemRef.parse(""));
        assertNull(ItemRef.parse("a b"));
        assertNull(ItemRef.parse("a:b:c:d"));
        assertNull(ItemRef.parse("a:b:notanumber"));
        assertNull(ItemRef.parse("x*0"));
        assertNull(ItemRef.parse("x*many"));
        assertNull(ItemRef.parse("ore:"));
        assertNull(ItemRef.parse(":x"));
    }

    @Test
    void numbersTooLargeForAnIntAreMalformedNotErrors() {
        assertNull(ItemRef.parse("99999999999"));
        assertNull(ItemRef.parse("265:99999999999"));
        assertNull(ItemRef.parse("minecraft:stone:99999999999"));
    }
}
