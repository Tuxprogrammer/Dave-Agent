package com.tuxprogrammer.davebridge.server.chat.markup;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class FontWidthsTest {

    @Test
    void matchesTheDefaultFont() {
        // advances from 1.7.10 ascii.png: "<Dave> " = 5+6+6+6+6+5+4
        assertEquals(38, FontWidths.width("<Dave> ", false));
        assertEquals(2, FontWidths.width('i', false));
        assertEquals(4, FontWidths.width(' ', false));
        assertEquals(7, FontWidths.width('@', false));
        assertEquals(7, FontWidths.width('A', true));
        assertEquals(FontWidths.OTHER, FontWidths.width('•', false));
    }

    @Test
    void fitCountsCharacters() {
        assertEquals(3, FontWidths.fit("abcdef", false, 18));
        assertEquals(2, FontWidths.fit("abcdef", false, 17));
        assertEquals(0, FontWidths.fit("abc", false, 5));
    }
}
