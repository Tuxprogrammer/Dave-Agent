package com.tuxprogrammer.davebridge.server.chat.markup;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import net.minecraft.event.ClickEvent;
import net.minecraft.event.HoverEvent;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;

import org.junit.jupiter.api.Test;

/** Renderer tests with a fake game: items/quests resolve from a fixed table, everything else is real. */
class MarkupRendererTest {

    /** Fake game objects. "steel" resolves; quests resolve to a token on their own line. */
    static final class FakeGame implements StandardLinkResolver.GameObjects {

        final List<String> sent = new ArrayList<>();

        @Override
        public ResolvedLink item(Markup.Token t, List<String> w) {
            if (t.arg.equals("gregtech:boom")) {
                // e.g. a mod item whose display name touches a client-only class on the server
                throw new NoClassDefFoundError("net/minecraft/client/resources/I18n");
            }
            if (!t.arg.equals("gregtech:steel")) {
                w.add("unknown item " + t.arg);
                return null;
            }
            IChatComponent base = new ChatComponentText(t.label != null ? t.label : "[Steel Ingot]");
            base.getChatStyle()
                .setColor(EnumChatFormatting.WHITE)
                .setChatHoverEvent(new HoverEvent(HoverEvent.Action.SHOW_ITEM, new ChatComponentText("{id:1s}")));
            IChatComponent vanilla = base.createCopy();
            vanilla.getChatStyle()
                .setChatClickEvent(new ClickEvent(ClickEvent.Action.RUN_COMMAND, "/nei_bookmark dave1"));
            IChatComponent mod = base.createCopy();
            mod.getChatStyle()
                .setChatClickEvent(
                    new ClickEvent(ClickEvent.Action.RUN_COMMAND, "/davebridge nei " + t.kind + " gregtech:steel:0"));
            return new ResolvedLink(vanilla, mod, false, Collections.singletonList(p -> sent.add("payload")));
        }

        @Override
        public ResolvedLink fluid(Markup.Token t, List<String> w) {
            return null;
        }

        @Override
        public ResolvedLink chain(Markup.Token t, List<String> w) {
            return null;
        }

        @Override
        public ResolvedLink quest(Markup.Token t, List<String> w) {
            IChatComponent c = new ChatComponentText("betterquesting.msg.sharequest:AAAAAAAAAAAAAAAAAAAAAA==");
            return new ResolvedLink(c, c, true, null);
        }

        @Override
        public ResolvedLink player(Markup.Token t, List<String> w) {
            return null;
        }
    }

    static MarkupRenderer renderer(int width, int maxLines) {
        StandardLinkResolver.Options o = new StandardLinkResolver.Options();
        o.waypoints = true;
        o.guides = true;
        // width in full-width (6 px) characters, for readable tests
        return new MarkupRenderer(new StandardLinkResolver(o, new FakeGame()), width * 6, width * 6, maxLines);
    }

    static List<IChatComponent> flat(IChatComponent line) {
        List<IChatComponent> out = new ArrayList<>();
        for (Object o : line.getSiblings()) out.add((IChatComponent) o);
        return out;
    }

    /** The innermost component holding {@code text} (typed links nest the link under a "Type: " wrapper). */
    static IChatComponent find(IChatComponent line, String text) {
        for (IChatComponent c : flat(line)) {
            if (c.getUnformattedText()
                .contains(text)) {
                IChatComponent inner = find(c, text);
                return inner != null ? inner : c;
            }
        }
        return null;
    }

    @Test
    void itemLinksDifferPerVariant() {
        MarkupRenderer.Rendered r = renderer(200, 40).render("Use {item:gregtech:steel} here");
        assertEquals(1, r.vanillaLines.size());
        IChatComponent v = find(r.vanillaLines.get(0), "Steel Ingot");
        IChatComponent m = find(r.modLines.get(0), "Steel Ingot");
        assertEquals(
            "/nei_bookmark dave1",
            v.getChatStyle()
                .getChatClickEvent()
                .getValue());
        assertEquals(
            "/davebridge nei item gregtech:steel:0",
            m.getChatStyle()
                .getChatClickEvent()
                .getValue());
        assertEquals(
            HoverEvent.Action.SHOW_ITEM,
            v.getChatStyle()
                .getChatHoverEvent()
                .getAction());
        assertEquals(1, r.actions.size());
        assertEquals(
            "Use [Steel Ingot] here",
            r.vanillaLines.get(0)
                .getUnformattedText());
    }

    @Test
    void unresolvedTokensDegradeToTextWithWarning() {
        MarkupRenderer.Rendered r = renderer(200, 40).render("Use {b}{item:nope:thing|Mystery}{/b}.");
        assertEquals(
            "Use Mystery.",
            r.vanillaLines.get(0)
                .getUnformattedText());
        IChatComponent mystery = find(r.vanillaLines.get(0), "Mystery");
        assertNull(
            mystery.getChatStyle()
                .getChatClickEvent());
        assertTrue(
            mystery.getChatStyle()
                .getBold());
        assertTrue(
            r.warnings.toString()
                .contains("unknown item"));
    }

    @Test
    void questNeverSharesALineWithOtherLinks() {
        MarkupRenderer.Rendered text = renderer(200, 40).render("Do {quest:Steel} then rest");
        assertEquals(1, text.vanillaLines.size());
        assertTrue(
            text.vanillaLines.get(0)
                .getUnformattedText()
                .startsWith("Do Quest: betterquesting.msg.sharequest:"));

        MarkupRenderer.Rendered links = renderer(200, 40)
            .render("{item:gregtech:steel} and {quest:Steel} and {item:gregtech:steel}");
        assertEquals(3, links.vanillaLines.size());
        assertTrue(
            links.vanillaLines.get(1)
                .getUnformattedText()
                .startsWith("Quest: betterquesting.msg.sharequest:"));
    }

    @Test
    void widthBreaksBecomeContinuationLinesAndBlankLinesDrop() {
        // Lines are cut at spaces to fit the chat box (120 px here), so the client never splits a word; the extra
        // lines are marked continued (indented, no <Dave>). Dave's own newlines start new prefixed lines.
        String markup = "aaaa bbbb cccc dddd eeee ffff {item:gregtech:steel|Steel Ingot Label} gggg\n\n\nend";
        MarkupRenderer.Rendered r = renderer(20, 40).render(markup);
        List<String> texts = new ArrayList<>();
        for (IChatComponent c : r.vanillaLines) texts.add(c.getUnformattedText());
        assertEquals(
            java.util.Arrays.asList("aaaa bbbb cccc dddd", "eeee ffff", "Steel Ingot Label gggg", "end"),
            texts);
        assertEquals(java.util.Arrays.asList(false, true, true, false), r.continued);
        assertNotNull(find(r.vanillaLines.get(2), "Steel Ingot Label"), "token text must be intact");
    }

    @Test
    void wordsMoveWholeAcrossStyles() {
        // "45s)" is one word in two styles: it moves to the next line whole instead of breaking at the color change
        MarkupRenderer.Rendered r = renderer(20, 40).render("aaaa bbbb cccc ddd (45s) more");
        assertEquals(
            "aaaa bbbb cccc ddd",
            r.vanillaLines.get(0)
                .getUnformattedText());
        assertEquals(
            "(45s) more",
            r.vanillaLines.get(1)
                .getUnformattedText());
    }

    @Test
    void wordsWiderThanALineAreCutAtLineEnds() {
        String word = "x" + new String(new char[45]).replace("\0", "y");
        MarkupRenderer.Rendered r = renderer(20, 40).render(word);
        assertEquals(3, r.vanillaLines.size());
        StringBuilder joined = new StringBuilder();
        for (IChatComponent c : r.vanillaLines) joined.append(c.getUnformattedText());
        assertEquals(word, joined.toString());
        assertEquals(java.util.Arrays.asList(false, true, true), r.continued);
    }

    @Test
    void truncatesLongMessages() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 10; i++) sb.append("line ")
            .append(i)
            .append('\n');
        MarkupRenderer.Rendered r = renderer(200, 4).render(sb.toString());
        assertEquals(4, r.vanillaLines.size());
        assertEquals(
            MarkupRenderer.TRUNCATED,
            r.vanillaLines.get(3)
                .getUnformattedText());
        assertTrue(
            r.warnings.toString()
                .contains("cut"));
    }

    @Test
    void hoverTokenSupportsStylesAndNewlines() {
        MarkupRenderer.Rendered r = renderer(200, 40).render("{hover:**Hot**\\nIt burns|Lava}");
        IChatComponent lava = find(r.vanillaLines.get(0), "Lava");
        HoverEvent h = lava.getChatStyle()
            .getChatHoverEvent();
        assertEquals(HoverEvent.Action.SHOW_TEXT, h.getAction());
        assertEquals(
            "Hot\nIt burns",
            h.getValue()
                .getUnformattedText());
        assertTrue(
            lava.getChatStyle()
                .getUnderlined());
    }

    @Test
    void hoverTextMayUseTags() {
        MarkupRenderer.Rendered r = renderer(200, 40).render("{hover:{red}Warning{/}: hot\\nsecond|lava} after");
        assertEquals(
            "lava after",
            r.vanillaLines.get(0)
                .getUnformattedText());
        IChatComponent hover = find(r.vanillaLines.get(0), "lava").getChatStyle()
            .getChatHoverEvent()
            .getValue();
        assertEquals("Warning: hot\nsecond", hover.getUnformattedText());
        IChatComponent warning = find(hover, "Warning");
        assertEquals(
            EnumChatFormatting.RED,
            warning.getChatStyle()
                .getColor());
        assertTrue(r.warnings.isEmpty(), r.warnings.toString());
    }

    @Test
    void aThrowingTokenDegradesAloneWithAWarning() {
        MarkupRenderer.Rendered r = renderer(200, 40).render("{item:gregtech:boom|Boom} and {item:gregtech:steel}");
        assertEquals(
            "Boom and [Steel Ingot]",
            r.vanillaLines.get(0)
                .getUnformattedText());
        assertTrue(
            r.warnings.toString()
                .contains("NoClassDefFoundError"),
            r.warnings.toString());
    }

    @Test
    void hugeMarkupIsCutBeforeParsing() {
        MarkupRenderer renderer = renderer(20, 2);
        int cap = renderer.maxMarkupLength();
        StringBuilder sb = new StringBuilder();
        while (sb.length() < cap * 3) sb.append("*a ");
        MarkupRenderer.Rendered r = renderer.render(sb.toString());
        assertTrue(
            r.warnings.get(0)
                .contains("markup longer than " + cap),
            r.warnings.toString());
        assertEquals(2, r.vanillaLines.size());
    }

    @Test
    void backslashNInALabelIsASpace() {
        MarkupRenderer.Rendered r = renderer(200, 40).render("{url:https://a.example/x|two\\nwords}");
        assertEquals(
            "two words",
            r.vanillaLines.get(0)
                .getUnformattedText());
    }

    @Test
    void stylesBecomeChatStyles() {
        MarkupRenderer.Rendered r = renderer(200, 40).render("{gold}**Hi**{/gold}");
        IChatComponent hi = find(r.vanillaLines.get(0), "Hi");
        assertEquals(
            EnumChatFormatting.GOLD,
            hi.getChatStyle()
                .getColor());
        assertTrue(
            hi.getChatStyle()
                .getBold());
    }

    @Test
    void followUpButtons() {
        MarkupRenderer.Rendered r = renderer(200, 40)
            .render("{send:dave, show the full chain|Full chain} {suggest:dave, why |Why?} {cmd:/dave status|Status}");
        IChatComponent line = r.vanillaLines.get(0);
        assertEquals("Ask: [Full chain] [Why?] [Status]", line.getUnformattedText());
        IChatComponent send = find(line, "Full chain");
        assertEquals(
            ClickEvent.Action.RUN_COMMAND,
            send.getChatStyle()
                .getChatClickEvent()
                .getAction());
        assertEquals(
            "dave, show the full chain",
            send.getChatStyle()
                .getChatClickEvent()
                .getValue());
        assertEquals(
            ClickEvent.Action.SUGGEST_COMMAND,
            find(line, "Why?").getChatStyle()
                .getChatClickEvent()
                .getAction());
        assertNotNull(
            find(line, "Status").getChatStyle()
                .getChatHoverEvent());
    }

    @Test
    void plainTextGetsTierAndNumberHighlights() {
        IChatComponent line = renderer(320, 10)
            .render("Cut it in a {m:Cutting Machine} (HV, 480 EU/t) {gold}at 5s{/}").modLines.get(0);
        assertEquals(
            EnumChatFormatting.YELLOW,
            find(line, "HV").getChatStyle()
                .getColor());
        assertEquals(
            EnumChatFormatting.YELLOW,
            find(line, "480 EU/t").getChatStyle()
                .getColor());
        assertEquals(
            EnumChatFormatting.AQUA,
            find(line, "Cutting Machine").getChatStyle()
                .getColor());
        // Dave's own colors win: no highlight inside {gold}
        assertEquals(
            EnumChatFormatting.GOLD,
            find(line, "at 5s").getChatStyle()
                .getColor());
        assertEquals("Cut it in a Cutting Machine (HV, 480 EU/t) at 5s", line.getUnformattedText());
    }
}
