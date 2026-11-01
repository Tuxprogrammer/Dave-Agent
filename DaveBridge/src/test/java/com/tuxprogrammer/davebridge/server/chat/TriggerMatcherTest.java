package com.tuxprogrammer.davebridge.server.chat;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

class TriggerMatcherTest {

    private static final String[] DEFAULTS = { "dave,", "@dave", "!dave" };

    @Test
    void matchesEachDefaultPrefixCaseInsensitively() {
        assertEquals("what is this?", TriggerMatcher.match("Dave, what is this?", DEFAULTS));
        assertEquals("help", TriggerMatcher.match("@DAVE help", DEFAULTS));
        assertEquals("status", TriggerMatcher.match("!dave status", DEFAULTS));
    }

    @Test
    void stripsSeparatorsAfterPrefix() {
        assertEquals("hi", TriggerMatcher.match("@dave: hi", DEFAULTS));
        assertEquals("hi", TriggerMatcher.match("@dave,  hi", DEFAULTS));
    }

    @Test
    void bareTriggerYieldsEmptyPrompt() {
        assertEquals("", TriggerMatcher.match("@dave", DEFAULTS));
    }

    @Test
    void ignoresLeadingWhitespace() {
        assertEquals("yo", TriggerMatcher.match("   dave, yo", DEFAULTS));
    }

    @Test
    void doesNotMatchLongerWords() {
        assertNull(TriggerMatcher.match("@davey hi", DEFAULTS));
        assertNull(TriggerMatcher.match("!daveed", DEFAULTS));
    }

    @Test
    void doesNotMatchMidSentenceOrWithoutComma() {
        assertNull(TriggerMatcher.match("hey dave, hi", DEFAULTS));
        assertNull(TriggerMatcher.match("dave hi", DEFAULTS));
        assertNull(TriggerMatcher.match("daveed, hi", DEFAULTS));
    }

    @Test
    void handlesNullsAndBlankPrefixes() {
        assertNull(TriggerMatcher.match(null, DEFAULTS));
        assertNull(TriggerMatcher.match("dave, x", null));
        assertNull(TriggerMatcher.match("dave, x", new String[] { "", null, "  " }));
    }
}
