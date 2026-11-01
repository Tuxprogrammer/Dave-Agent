package com.tuxprogrammer.davebridge.client;

import net.minecraft.client.Minecraft;
import net.minecraft.event.ClickEvent;
import net.minecraft.event.HoverEvent;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatComponentTranslation;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;

import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.ClientSettings;

/**
 * The client-eval opt-in: the join nudge, {@code /davebridge optin|optout|status} and telling the server when the
 * choice changes mid-session. Client thread only.
 */
final class OptIn {

    /** Wait after joining before nudging, so the line is not buried under the pack's own login messages. */
    static final int NUDGE_DELAY_TICKS = 100;

    private OptIn() {}

    /**
     * Called once per connection when the server answered our hello: schedule the nudge if the player has not chosen.
     */
    static void onServerHello() {
        ClientState.nudgeTicks = !ClientConfig.clientEvalAllowed && ClientConfig.optInReminder ? NUDGE_DELAY_TICKS : 0;
    }

    /** Called every client tick. */
    static void tick() {
        if (ClientState.nudgeTicks > 0 && --ClientState.nudgeTicks == 0
            && ClientState.serverHasMod
            && !ClientConfig.clientEvalAllowed) {
            showNudge();
        }
    }

    static void set(boolean allowed) {
        boolean changed = ClientConfig.clientEvalAllowed != allowed;
        ClientConfig.setClientEvalAllowed(allowed);
        ClientState.nudgeTicks = 0;
        if (changed) {
            tellServer();
        }
    }

    /** Sends the current opt-in to the server if we are on one that runs DaveBridge. */
    static void tellServer() {
        if (ClientState.serverHasMod && Minecraft.getMinecraft().thePlayer != null) {
            ClientSettings settings = new ClientSettings();
            settings.clientEvalAllowed = ClientConfig.clientEvalAllowed;
            DaveNetwork.sendToServer(settings);
        }
    }

    static void showNudge() {
        DaveChatRenderer.print(
            DaveChatRenderer.tag(ClientState.botName, null)
                .appendSibling(new ChatComponentTranslation("davebridge.optin.nudge", ClientState.botName)));
        IChatComponent buttons = new ChatComponentText("  ");
        buttons.appendSibling(
            button(
                "davebridge.optin.button.yes",
                EnumChatFormatting.GREEN,
                "/davebridge optin",
                "davebridge.optin.button.yes.hover"));
        buttons.appendSibling(new ChatComponentText("  "));
        buttons.appendSibling(
            button(
                "davebridge.optin.button.no",
                EnumChatFormatting.GRAY,
                "/davebridge optout",
                "davebridge.optin.button.no.hover"));
        DaveChatRenderer.print(buttons);
    }

    static IChatComponent status() {
        return new ChatComponentTranslation(
            ClientConfig.clientEvalAllowed ? "davebridge.optin.status.on" : "davebridge.optin.status.off",
            ClientState.botName);
    }

    private static IChatComponent button(String key, EnumChatFormatting color, String command, String hoverKey) {
        IChatComponent c = new ChatComponentTranslation(key);
        c.setChatStyle(
            new ChatStyle().setColor(color)
                .setBold(Boolean.TRUE)
                .setChatClickEvent(new ClickEvent(ClickEvent.Action.RUN_COMMAND, command))
                .setChatHoverEvent(
                    new HoverEvent(HoverEvent.Action.SHOW_TEXT, new ChatComponentTranslation(hoverKey))));
        return c;
    }
}
