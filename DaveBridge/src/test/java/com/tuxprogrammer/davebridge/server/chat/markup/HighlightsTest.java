package com.tuxprogrammer.davebridge.server.chat.markup;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;

import org.junit.jupiter.api.Test;

class HighlightsTest {

    /** Spans as text, highlighted ones in [brackets]. */
    private static String marked(String text) {
        StringBuilder sb = new StringBuilder();
        List<Highlights.Span> spans = Highlights.split(text);
        for (Highlights.Span s : spans) sb.append(s.style == null ? s.text : "[" + s.text + "]");
        return sb.toString();
    }

    @Test
    void numbersWithUnits() {
        assertEquals("Laser Engraver ([HV], [480 EU/t], [45s])", marked("Laser Engraver (HV, 480 EU/t, 45s)"));
        assertEquals("using [135 L] Lubricant ([7.5s])", marked("using 135 L Lubricant (7.5s)"));
        assertEquals("You get [16] NOR chips, [x16] or [1,200 L]", marked("You get 16 NOR chips, x16 or 1,200 L"));
        assertEquals("[2-4] EBFs at [1.2M EU]", marked("2-4 EBFs at 1.2M EU"));
        assertEquals("base at [1200] [70] [-800]", marked("base at 1200 70 -800"));
    }

    @Test
    void tiersGetTheirGtColors() {
        List<Highlights.Span> spans = Highlights.split("HV or LuV");
        assertEquals("yellow", spans.get(0).style[0]);
        assertEquals("light_purple", spans.get(2).style[0]);
        assertEquals("[LV]/[MV] and [UHV]", marked("LV/MV and UHV"));
    }

    @Test
    void leavesWordsAndIdsAlone() {
        assertEquals("T1 MK2 GTNH 2.9.0 HVAC Lens Assembler", marked("T1 MK2 GTNH 2.9.0 HVAC Lens Assembler"));
        assertEquals("[1] Lens and [2] Assemblers", marked("1 Lens and 2 Assemblers"));
    }

    @Test
    void spansRebuildTheText() {
        String s = "Cut the array in a Cutting Machine (HV, 480 EU/t, 5s) with Programmed Circuit 1.";
        StringBuilder sb = new StringBuilder();
        for (Highlights.Span span : Highlights.split(s)) sb.append(span.text);
        assertEquals(s, sb.toString());
    }
}
