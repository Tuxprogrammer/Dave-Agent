package com.tuxprogrammer.davebridge.server.chat;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.junit.jupiter.api.Test;

class ChatTextTest {

    @Test
    void splitsOnNewlinesAndDropsBlankLines() {
        assertEquals(Arrays.asList("a", "b", "c"), ChatText.toLines("a\r\nb\n\n  \nc\r", 100, 10));
    }

    @Test
    void wrapsAtSpaces() {
        List<String> lines = ChatText.toLines("aaaa bbbb cccc dddd", 10, 10);
        assertEquals(Arrays.asList("aaaa bbbb", "cccc dddd"), lines);
        for (String line : lines) {
            assertTrue(line.length() <= 10);
        }
    }

    @Test
    void hardCutsWordsLongerThanALine() {
        assertEquals(Arrays.asList("abcdefghij", "klmno"), ChatText.toLines("abcdefghijklmno", 10, 10));
    }

    @Test
    void truncatesTooManyLines() {
        List<String> lines = ChatText.toLines("1\n2\n3\n4\n5", 100, 3);
        assertEquals(Arrays.asList("1", "2", ChatText.TRUNCATED), lines);
    }

    @Test
    void truncationIsReportedAsAWarning() {
        List<String> warnings = new ArrayList<>();
        ChatText.toLines("1\n2\n3\n4\n5", 100, 3, warnings);
        assertEquals(1, warnings.size());
        assertTrue(
            warnings.get(0)
                .contains("cut to 3 lines"));
        warnings.clear();
        ChatText.toLines("1\n2", 100, 3, warnings);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void replacesControlCharacters() {
        assertEquals(Arrays.asList("a b    c"), ChatText.toLines("a\u0007b\tc", 100, 10));
    }

    @Test
    void nullOrEmptyGivesNoLines() {
        assertTrue(
            ChatText.toLines(null, 10, 10)
                .isEmpty());
        assertTrue(
            ChatText.toLines("\n \n", 10, 10)
                .isEmpty());
    }
}
