package com.tuxprogrammer.davebridge.server.chat;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

class TriggerMatcherTest {

    private static final String[] DEFAULTS = { "dave", "@dave", "!dave" };

    @Test
    void matchesEachDefaultPrefixCaseInsensitively() {
        assertEquals("what is this?", TriggerMatcher.match("Dave, what is this?", DEFAULTS));
        assertEquals(
            "how do I make NOR and NAND chips?",
            TriggerMatcher.match("Dave how do I make NOR and NAND chips?", DEFAULTS));
        assertEquals("hi", TriggerMatcher.match("dave: hi", DEFAULTS));
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
        assertNull(TriggerMatcher.match("davey, hi", DEFAULTS));
    }

    @Test
    void doesNotMatchPossessive() {
        assertNull(TriggerMatcher.match("dave's base is up north", DEFAULTS));
        assertNull(TriggerMatcher.match("Dave’s idea worked", DEFAULTS));
    }

    @Test
    void doesNotMatchMidSentence() {
        assertNull(TriggerMatcher.match("hey dave, hi", DEFAULTS));
        assertNull(TriggerMatcher.match("ask dave about it", DEFAULTS));
    }

    @Test
    void addressedAcceptsGreetingBeforeName() {
        assertEquals("how do I make steel?", TriggerMatcher.addressed("hey Dave, how do I make steel?", DEFAULTS));
        assertEquals("where is titanium", TriggerMatcher.addressed("ok dave where is titanium", DEFAULTS));
        assertEquals("help", TriggerMatcher.addressed("hi @dave help", DEFAULTS));
    }

    @Test
    void addressedAcceptsNameAtTheEnd() {
        assertEquals("how do I make steel?", TriggerMatcher.addressed("how do I make steel, dave?", DEFAULTS));
        assertEquals("where is my base", TriggerMatcher.addressed("where is my base Dave", DEFAULTS));
    }

    @Test
    void addressedKeepsTheWholeLineWhenOnlyTheNameIsLeft() {
        assertEquals("thanks dave", TriggerMatcher.addressed("thanks dave", DEFAULTS));
        assertEquals("Dave?", TriggerMatcher.addressed("Dave?", DEFAULTS));
        assertEquals("dave", TriggerMatcher.addressed("  dave ", DEFAULTS));
    }

    @Test
    void addressedStillIgnoresOtherChat() {
        assertNull(TriggerMatcher.addressed("hey everyone", DEFAULTS));
        assertNull(TriggerMatcher.addressed("is that dave's base?", DEFAULTS));
        assertNull(TriggerMatcher.addressed("high voltage", DEFAULTS));
        assertNull(TriggerMatcher.addressed("davey is here", DEFAULTS));
        assertNull(TriggerMatcher.addressed("ask dave about it", DEFAULTS));
        assertNull(TriggerMatcher.addressed(null, DEFAULTS));
    }

    @Test
    void matchStaysStartOnly() {
        // {send:} links and other checks rely on match() needing the prefix first.
        assertNull(TriggerMatcher.match("hey dave, hi", DEFAULTS));
        assertNull(TriggerMatcher.match("/kill dave", DEFAULTS));
    }

    @Test
    void handlesNullsAndBlankPrefixes() {
        assertNull(TriggerMatcher.match(null, DEFAULTS));
        assertNull(TriggerMatcher.match("dave, x", null));
        assertNull(TriggerMatcher.match("dave, x", new String[] { "", null, "  " }));
    }
}
