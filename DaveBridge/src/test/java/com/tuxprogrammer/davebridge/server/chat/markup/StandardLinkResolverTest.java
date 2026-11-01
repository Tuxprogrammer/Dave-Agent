package com.tuxprogrammer.davebridge.server.chat.markup;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;

import net.minecraft.event.ClickEvent;
import net.minecraft.util.IChatComponent;

import org.junit.jupiter.api.Test;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

class StandardLinkResolverTest {

    private final List<String> warnings = new ArrayList<>();

    private static Markup.Token token(String markup) {
        for (Markup.Node n : Markup.parse(markup).nodes) {
            if (n instanceof Markup.Token) return (Markup.Token) n;
        }
        throw new AssertionError("no token in " + markup);
    }

    private ResolvedLink resolve(StandardLinkResolver.Options o, String markup) {
        return new StandardLinkResolver(o, new MarkupRendererTest.FakeGame()).resolve(token(markup), warnings);
    }

    private ResolvedLink resolve(String markup) {
        StandardLinkResolver.Options o = new StandardLinkResolver.Options();
        o.waypoints = true;
        o.guides = true;
        return resolve(o, markup);
    }

    /** The first click in the link's component tree (typed links put the clickable part after a grey type word). */
    private static ClickEvent click(ResolvedLink l) {
        return click(l.vanilla);
    }

    private static ClickEvent click(IChatComponent c) {
        if (c.getChatStyle()
            .getChatClickEvent() != null) {
            return c.getChatStyle()
                .getChatClickEvent();
        }
        for (Object sibling : c.getSiblings()) {
            ClickEvent e = click((IChatComponent) sibling);
            if (e != null) return e;
        }
        return null;
    }

    @Test
    void typedLinksSayWhatTheyAre() {
        assertEquals("Ask: [More]", resolve("{send:dave, more|More}").vanilla.getUnformattedText());
        assertEquals("Guide: [GT guide]", resolve("{guide:gregtech:main|GT guide}").vanilla.getUnformattedText());
        assertTrue(
            resolve("{waypoint:100,64,-200,-1|Base}").vanilla.getUnformattedText()
                .startsWith("Waypoint: [Base"));
        // no type word where the label reads fine inline
        assertEquals(
            "wiki",
            resolve("{url:https://wiki.gtnewhorizons.com/wiki/Steel|wiki}").vanilla.getUnformattedText());
    }

    @Test
    void urls() {
        ResolvedLink l = resolve("{url:https://wiki.gtnewhorizons.com/wiki/Steel|wiki}");
        assertEquals(ClickEvent.Action.OPEN_URL, click(l).getAction());
        assertEquals("wiki", l.vanilla.getUnformattedText());
        assertNull(resolve("{url:javascript:alert(1)}"));
        assertNull(resolve("{url:file:///etc/passwd}"));
        assertNull(resolve("{url:not a url}"));
        assertEquals(3, warnings.size());
    }

    @Test
    void urlAllowlistMatchesDomainSuffixes() {
        String[] allow = { "gtnewhorizons.com" };
        assertNull(StandardLinkResolver.checkUrl("https://wiki.gtnewhorizons.com/x", allow));
        assertNull(StandardLinkResolver.checkUrl("https://gtnewhorizons.com", allow));
        assertNotNull(StandardLinkResolver.checkUrl("https://evilgtnewhorizons.com", allow));
        assertNotNull(StandardLinkResolver.checkUrl("https://example.org", allow));
    }

    @Test
    void commandsMustBeAllowlisted() {
        assertNotNull(resolve("{cmd:/dave status|Status}"));
        assertNull(resolve("{cmd:/op Steve|Op}"));
        assertNull(resolve("{cmd:dave status}"));
        assertNull(resolve("{cmd:/dave " + new String(new char[120]).replace("\0", "x") + "}"));
        assertNull(StandardLinkResolver.checkCommand("/bq_client show abc", new String[] { "/bq_client" }));
    }

    @Test
    void sendNeedsATriggerPrefixElseBecomesASuggestion() {
        ResolvedLink ok = resolve("{send:dave, more|More}");
        assertEquals(ClickEvent.Action.RUN_COMMAND, click(ok).getAction());
        ResolvedLink notDave = resolve("{send:hello everyone|Hi}");
        assertEquals(ClickEvent.Action.SUGGEST_COMMAND, click(notDave).getAction());
        ResolvedLink clientCmd = resolve("{send:bq_client show x|x}");
        assertEquals(ClickEvent.Action.SUGGEST_COMMAND, click(clientCmd).getAction());
        assertEquals(2, warnings.size());
    }

    @Test
    void chatSafety() {
        assertTrue(StandardLinkResolver.isChatSafe("dave, hi!"));
        assertTrue(!StandardLinkResolver.isChatSafe("§cred"));
        assertTrue(!StandardLinkResolver.isChatSafe("a\tb"));
    }

    @Test
    void waypointsUseShareWhereIAmFormat() {
        ResolvedLink l = resolve("{waypoint:100,64,-200,-1|Base}");
        String cmd = click(l).getValue();
        assertTrue(cmd.startsWith("/savewaypoint "));
        String json = new String(
            Base64.getDecoder()
                .decode(cmd.substring("/savewaypoint ".length())),
            StandardCharsets.UTF_8);
        JsonObject o = new JsonParser().parse(json)
            .getAsJsonObject();
        assertEquals(
            "Base",
            o.get("name")
                .getAsString());
        assertEquals(
            800,
            o.get("x")
                .getAsInt()); // nether coordinates stored in overworld scale
        assertEquals(
            -1,
            o.get("primaryDimension")
                .getAsInt());
        assertEquals(
            "Base_800,64,-1600",
            o.get("id")
                .getAsString());
        assertNull(resolve("{waypoint:1,2}"));
    }

    @Test
    void waypointsWithoutTheModAreTextOnly() {
        StandardLinkResolver.Options o = new StandardLinkResolver.Options();
        ResolvedLink l = resolve(o, "{waypoint:1,2,3|Here}");
        assertNull(click(l));
        IChatComponent c = l.vanilla;
        assertTrue(
            c.getUnformattedText()
                .contains("1, 2, 3"));
    }

    @Test
    void guides() {
        assertEquals("/guidenhc open gregtech:main", click(resolve("{guide:gregtech:main|GT guide}")).getValue());
        assertNull(resolve("{guide:Not An Id}"));
        assertNull(resolve(new StandardLinkResolver.Options(), "{guide:gregtech:main}"));
    }
}
