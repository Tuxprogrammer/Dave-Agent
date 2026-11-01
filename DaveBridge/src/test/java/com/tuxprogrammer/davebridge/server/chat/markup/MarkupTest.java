package com.tuxprogrammer.davebridge.server.chat.markup;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.List;

import org.junit.jupiter.api.Test;

class MarkupTest {

    private static List<Markup.Node> nodes(String s) {
        return Markup.parse(s).nodes;
    }

    private static String plain(String s) {
        StringBuilder sb = new StringBuilder();
        for (Markup.Node n : nodes(s)) {
            if (n instanceof Markup.Text) sb.append(((Markup.Text) n).text);
            else if (n instanceof Markup.Newline) sb.append('\n');
            else sb.append('<')
                .append(((Markup.Token) n).kind)
                .append('>');
        }
        return sb.toString();
    }

    private static Markup.Text textNode(String s, String containing) {
        for (Markup.Node n : nodes(s)) {
            if (n instanceof Markup.Text && ((Markup.Text) n).text.contains(containing)) return (Markup.Text) n;
        }
        throw new AssertionError("no text node containing " + containing + " in " + nodes(s));
    }

    private static List<Markup.Token> tokens(String s) {
        List<Markup.Token> out = new ArrayList<>();
        for (Markup.Node n : nodes(s)) if (n instanceof Markup.Token) out.add((Markup.Token) n);
        return out;
    }

    @Test
    void plainTextIsOneNode() {
        List<Markup.Node> n = nodes("hello world");
        assertEquals(1, n.size());
        assertTrue(((Markup.Text) n.get(0)).style.isPlain());
    }

    @Test
    void markdownSpans() {
        assertTrue(textNode("a **bold** b", "bold").style.bold);
        assertTrue(textNode("a *it* b", "it").style.italic);
        assertTrue(textNode("a __under__ b", "under").style.underline);
        assertTrue(textNode("a ~~gone~~ b", "gone").style.strike);
        assertEquals("gray", textNode("run `make` now", "make").style.color);
        assertEquals("a bold b", plain("a **bold** b"));
    }

    @Test
    void lonelyOrSpacedDelimitersStayLiteral() {
        assertEquals("2 * 3 * 4", plain("2 * 3 * 4"));
        assertEquals("a *b", plain("a *b"));
        assertEquals("snake_case_name", plain("snake_case_name"));
    }

    @Test
    void tagSpansNestAndCrossLines() {
        String s = "{gold}gold {b}both{/b} gold\nstill gold{/gold} plain";
        assertEquals("gold", textNode(s, "gold ").style.color);
        Markup.Style both = textNode(s, "both").style;
        assertEquals("gold", both.color);
        assertTrue(both.bold);
        assertEquals("gold", textNode(s, "still").style.color);
        assertNull(textNode(s, "plain").style.color);
        assertTrue(Markup.parse(s).warnings.isEmpty());
    }

    @Test
    void colorFormsAndAliases() {
        assertEquals("red", textNode("{color:red}x{/}", "x").style.color);
        assertEquals("gold", textNode("{orange}x{/orange}", "x").style.color);
        assertEquals("gray", textNode("{grey}x{/}", "x").style.color);
        assertEquals("light_purple", textNode("{pink}x{/}", "x").style.color);
    }

    @Test
    void closeAllInnermostAndUnclosed() {
        Markup.Result r = Markup.parse("{red}{b}x{/} y{/} z {/}");
        assertTrue(
            r.warnings.toString()
                .contains("stray"),
            r.warnings.toString());
        Markup.Result unclosed = Markup.parse("{gold}never closed");
        assertTrue(
            unclosed.warnings.get(0)
                .contains("unclosed"));
    }

    @Test
    void tokensWithLabelsAndStyles() {
        List<Markup.Token> t = tokens(
            "Make {item:gregtech:gt.metaitem.01:11305|steel} in a {b}{quest:Steel|this quest}{/b}");
        assertEquals(2, t.size());
        assertEquals("item", t.get(0).kind);
        assertEquals("gregtech:gt.metaitem.01:11305", t.get(0).arg);
        assertEquals("steel", t.get(0).label);
        assertEquals("quest", t.get(1).kind);
        assertTrue(t.get(1).style.bold);
    }

    @Test
    void labelSplitsAtLastBarAndEscapes() {
        Markup.Token t = tokens("{hover:a|b|label}").get(0);
        assertEquals("a|b", t.arg);
        assertEquals("label", t.label);
        Markup.Token e = tokens("{suggest:x \\| y|lab\\}el}").get(0);
        assertEquals("x | y", e.arg);
        assertEquals("lab}el", e.label);
        // hover text stays raw (escapes included) until parseHoverText reads it
        Markup.Token h = tokens("{hover:x \\| y|lab\\}el}").get(0);
        assertEquals("x \\| y", h.arg);
        assertEquals("lab}el", h.label);
        assertEquals("x | y", ((Markup.Text) Markup.parseHoverText(h.arg).nodes.get(0)).text);
    }

    @Test
    void linkIsAnAliasForUrl() {
        assertEquals("url", tokens("{link:https://a.b}").get(0).kind);
    }

    @Test
    void unknownThingsStayLiteralWithWarnings() {
        Markup.Result r = Markup.parse("a {foo:bar} b {sparkle} c { d");
        assertEquals("a {foo:bar} b {sparkle} c { d", plain("a {foo:bar} b {sparkle} c { d"));
        assertEquals(3, r.warnings.size(), r.warnings.toString());
    }

    @Test
    void emptyTokenArgumentFallsBack() {
        Markup.Result r = Markup.parse("{item:|Steel}");
        assertTrue(tokens("{item:|Steel}").isEmpty());
        assertEquals("Steel", plain("{item:|Steel}"));
        assertFalse(r.warnings.isEmpty());
    }

    @Test
    void escapes() {
        assertEquals("{gold} *x* \\", plain("\\{gold\\} \\*x\\* \\\\"));
    }

    @Test
    void headingsBulletsAndBreaks() {
        assertTrue(textNode("# Title\nbody", "Title").style.bold);
        assertFalse(textNode("# Title\nbody", "body").style.bold);
        assertEquals("• one\n• two", plain("- one\n* two"));
        assertEquals("a\nb", plain("a{br}b"));
        assertEquals("a\nb", plain("a\r\nb"));
    }

    @Test
    void delimitersInsideLaterTokensAreNotClosers() {
        // the chain's "*4" must not close the "*" before "Note"
        String s = "*Note: grab {chain:minecraft:iron_ingot*4|kit} now";
        assertFalse(textNode(s, "Note").style.italic);
        assertEquals("*Note: grab <chain> now", plain(s));
        // a real closer after a token still counts
        assertTrue(tokens("**{item:gregtech:steel}**").get(0).style.bold);
    }

    @Test
    void strayAndUnknownClosersStayLiteral() {
        Markup.Result stray = Markup.parse("x {/} y");
        assertEquals("x {/} y", plain("x {/} y"));
        assertTrue(
            stray.warnings.toString()
                .contains("stray"));
        // an unknown closer does not silently close the open span
        assertEquals("gold", textNode("{gold}a {/foo} b", "b").style.color);
        assertEquals("a {/foo} b", plain("{gold}a {/foo} b"));
        assertTrue(
            Markup.parse("{gold}a {/foo} b").warnings.toString()
                .contains("unknown closing tag"));
        // {/color} closes the innermost color, {/color:red} that color
        assertNull(textNode("{color:red}{b}a{/color}b", "b").style.color);
        assertNull(textNode("{red}a{/color:red}b", "b").style.color);
        assertEquals("a{}b", plain("a{}b"));
    }

    @Test
    void hoverTextKeepsOneLevelOfTags() {
        String s = "{hover:{red}Warning{/}: hot|lava} after";
        List<Markup.Token> t = tokens(s);
        assertEquals(1, t.size());
        assertEquals("hover", t.get(0).kind);
        assertEquals("{red}Warning{/}: hot", t.get(0).arg);
        assertEquals("lava", t.get(0).label);
        assertTrue(Markup.parse(s).warnings.isEmpty());
        assertEquals("red", textNode(t.get(0).arg, "Warning").style.color);
        // a nested token's own label bar is not the hover's label
        Markup.Token nested = tokens("{hover:see {item:x|X}}").get(0);
        assertEquals("see {item:x|X}", nested.arg);
        assertNull(nested.label);
        // several tags in a row are one level; braces two levels deep are refused and stay literal
        assertEquals(1, tokens("{hover:{red}{b}x{/}{/}|y}").size());
        assertEquals("{hover:{item:{x}}|y}", plain("{hover:{item:{x}}|y}"));
        assertTrue(
            Markup.parse("{hover:{item:{x}}|y}").warnings.toString()
                .contains("unmatched"));
    }

    @Test
    void backslashNIsANewlineOnlyInHoverText() {
        Markup.Token t = tokens("{item:nope|Steel\\nIngot}").get(0);
        assertEquals("Steel Ingot", t.label);
        List<Markup.Node> hover = Markup.parseHoverText("a\\nb").nodes;
        assertEquals(3, hover.size());
        assertTrue(hover.get(1) instanceof Markup.Newline);
        assertEquals("anb", plain("a\\nb"));
    }

    @Test
    void nullAndEmpty() {
        assertTrue(nodes(null).isEmpty());
        assertTrue(nodes("").isEmpty());
    }
}
