package com.tuxprogrammer.davebridge.server.chat;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.List;

import net.minecraft.event.HoverEvent;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatComponentTranslation;
import net.minecraft.util.IChatComponent;

import org.junit.jupiter.api.Test;

import com.google.gson.JsonParser;
import com.tuxprogrammer.davebridge.server.bridge.ProtocolException;
import com.tuxprogrammer.davebridge.server.chat.markup.MarkupRenderer;

class DaveChatLinesTest {

    @Test
    void publicAndWhisperPrefixes() {
        IChatComponent pub = DaveChat.prefixed(new ChatComponentText("hi"), false);
        assertEquals("<Dave> hi", pub.getUnformattedText());
        IChatComponent whisper = DaveChat.prefixed(new ChatComponentText("hi"), true);
        IChatComponent prefix = (IChatComponent) whisper.getSiblings()
            .get(0);
        assertTrue(prefix instanceof ChatComponentTranslation);
        assertEquals("commands.message.display.incoming", ((ChatComponentTranslation) prefix).getKey());
        assertTrue(
            prefix.getChatStyle()
                .getItalic());
        // the body is a sibling of the root, not of the italic prefix, so it keeps its own style
        IChatComponent body = (IChatComponent) whisper.getSiblings()
            .get(1);
        assertEquals("hi", body.getUnformattedText());
    }

    @Test
    void oversizedLinesDegradeInSteps() {
        List<String> warnings = new ArrayList<>();
        IChatComponent line = new ChatComponentText("");
        for (int i = 0; i < 30; i++) {
            IChatComponent item = new ChatComponentText("[Item " + i + "]");
            item.getChatStyle()
                .setChatHoverEvent(
                    new HoverEvent(
                        HoverEvent.Action.SHOW_ITEM,
                        new ChatComponentText(new String(new char[2000]).replace("\0", "x"))));
            line.appendSibling(item);
        }
        assertTrue(DaveChat.jsonBytes(line) > DaveChat.MAX_LINE_JSON_BYTES);
        IChatComponent fitted = DaveChat.fit(line, warnings);
        assertTrue(DaveChat.jsonBytes(fitted) <= DaveChat.MAX_LINE_JSON_BYTES);
        assertEquals(line.getUnformattedText(), fitted.getUnformattedText());
        IChatComponent first = (IChatComponent) fitted.getSiblings()
            .get(0);
        assertEquals(
            HoverEvent.Action.SHOW_TEXT,
            first.getChatStyle()
                .getChatHoverEvent()
                .getAction());
        assertEquals(1, warnings.size());
    }

    @Test
    void bothVariantsDegradingReportsOnce() {
        IChatComponent line = new ChatComponentText("");
        for (int i = 0; i < 30; i++) {
            IChatComponent item = new ChatComponentText("[Item " + i + "]");
            item.getChatStyle()
                .setChatHoverEvent(
                    new HoverEvent(
                        HoverEvent.Action.SHOW_ITEM,
                        new ChatComponentText(new String(new char[2000]).replace("\0", "x"))));
            line.appendSibling(item);
        }
        List<String> warnings = new ArrayList<>();
        List<IChatComponent> mod = new ArrayList<>();
        List<IChatComponent> vanilla = new ArrayList<>();
        DaveChat.fitBoth(line, line.createCopy(), mod, vanilla, warnings);
        assertEquals(1, mod.size());
        assertEquals(1, vanilla.size());
        assertEquals(1, warnings.size(), warnings.toString());
    }

    @Test
    void droppedFileAndTwitchClicksAreWarnings() throws ProtocolException {
        List<String> warnings = new ArrayList<>();
        String json = "[{\"text\":\"f\",\"clickEvent\":{\"action\":\"open_file\",\"value\":\"/etc/x\"}},"
            + "{\"text\":\"t\",\"extra\":[{\"text\":\"tw\",\"clickEvent\":{\"action\":\"twitch_user_info\",\"value\":\"u\"}}]}]";
        MarkupRenderer.Rendered r = DaveChat.fromComponents(new JsonParser().parse(json), warnings);
        assertEquals(2, r.vanillaLines.size());
        assertEquals(2, warnings.size(), warnings.toString());
        assertTrue(
            warnings.get(0)
                .contains("open_file"));
        assertTrue(
            warnings.get(1)
                .contains("twitch_user_info"));
    }

    @Test
    void componentsEscapeHatchChecksClicks() throws ProtocolException {
        List<String> warnings = new ArrayList<>();
        String json = "[{\"text\":\"ok\",\"clickEvent\":{\"action\":\"run_command\",\"value\":\"/dave status\"}},"
            + "{\"text\":\"bad\",\"extra\":[{\"text\":\"op\",\"clickEvent\":{\"action\":\"run_command\",\"value\":\"/op me\"}},"
            + "{\"text\":\"js\",\"clickEvent\":{\"action\":\"open_url\",\"value\":\"javascript:x\"}}]}]";
        MarkupRenderer.Rendered r = DaveChat.fromComponents(new JsonParser().parse(json), warnings);
        assertEquals(2, r.vanillaLines.size());
        IChatComponent ok = (IChatComponent) r.vanillaLines.get(0)
            .getSiblings()
            .get(0);
        assertEquals(
            "/dave status",
            ok.getChatStyle()
                .getChatClickEvent()
                .getValue());
        IChatComponent bad = (IChatComponent) r.vanillaLines.get(1)
            .getSiblings()
            .get(0);
        for (Object s : bad.getSiblings()) {
            assertNull(
                ((IChatComponent) s).getChatStyle()
                    .getChatClickEvent());
        }
        assertEquals(2, warnings.size(), warnings.toString());
        assertThrows(
            ProtocolException.class,
            () -> DaveChat.fromComponents(new JsonParser().parse("[{\"bogus\":1}]"), new ArrayList<>()));
    }
}
