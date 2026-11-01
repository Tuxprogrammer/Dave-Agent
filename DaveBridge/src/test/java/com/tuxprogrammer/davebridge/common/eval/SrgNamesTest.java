package com.tuxprogrammer.davebridge.common.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.StringReader;
import java.util.Arrays;
import java.util.Collections;

import org.junit.jupiter.api.Test;

class SrgNamesTest {

    @Test
    void parsesAndMapsBothWays() throws Exception {
        SrgNames n = SrgNames.parse(
            new StringReader("# comment\nfield_1_a\tinventory\nfield_2_b\tinventory\nfunc_3_c\tgetHealth\nbad line\n"));
        assertEquals(3, n.size());
        assertEquals("inventory", n.mcp("field_1_a"));
        assertEquals(Arrays.asList("field_1_a", "field_2_b"), n.srg("inventory"));
        assertEquals(Collections.singletonList("func_3_c"), n.srgMethods("getHealth"));
        assertTrue(
            n.srgFields("getHealth")
                .isEmpty());
        assertEquals("unchanged", n.readable("unchanged"));
        assertEquals("getHealth", n.readable("func_3_c"));
    }

    @Test
    void bundledTableHasTheMappingsScriptsNeed() {
        SrgNames n = SrgNames.get();
        assertTrue(n.size() > 9000, "bundled table size " + n.size());
        assertTrue(
            n.srgFields("inventory")
                .contains("field_71071_by"));
        assertTrue(
            n.srgMethods("getHealth")
                .contains("func_110143_aJ"));
        assertEquals("posX", n.mcp("field_70165_t"));
    }
}
