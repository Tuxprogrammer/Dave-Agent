package com.tuxprogrammer.davebridge.client;

import net.minecraft.client.gui.GuiChat;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraftforge.client.ClientCommandHandler;

import com.google.gson.JsonObject;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.Ask;

/**
 * The chat line opened by the "Ask Dave" key. On a DaveBridge server the line is sent as an {@link Ask} packet with
 * the context captured when the key was pressed, and may be as long as the server's {@code maxAskLength} (sent in
 * {@code server_hello}) rather than vanilla's 100 characters. On any other server it behaves exactly like normal chat,
 * so a trigger prefix still reaches Dave through plain chat.
 */
public class GuiDaveChat extends GuiChat {

    /** Vanilla's chat packet silently cuts anything longer, which would mangle a command. */
    static final int VANILLA_CHAT_LIMIT = 100;

    private final JsonObject context;

    public GuiDaveChat(String prefill, JsonObject context) {
        super(prefill);
        this.context = context;
    }

    @Override
    public void initGui() {
        super.initGui();
        if (ClientState.serverHasMod) {
            inputField.setMaxStringLength(ClientState.maxAskLength);
        }
    }

    @Override
    public void func_146403_a(String message) {
        if (message.startsWith("/") && message.length() > VANILLA_CHAT_LIMIT) {
            // Only possible because the line allows long questions. Client commands have no limit; a server command
            // would be truncated by the chat packet, so refuse it instead of running half of it.
            mc.ingameGUI.getChatGUI()
                .addToSentMessages(message);
            if (ClientCommandHandler.instance.executeCommand(mc.thePlayer, message) == 0) {
                mc.ingameGUI.getChatGUI()
                    .printChatMessage(
                        new ChatComponentText(
                            "Commands are limited to " + VANILLA_CHAT_LIMIT + " characters; not sent.")
                                .setChatStyle(new ChatStyle().setColor(EnumChatFormatting.RED)));
            }
            return;
        }
        if (!ClientState.serverHasMod || message.startsWith("/")) {
            super.func_146403_a(message);
            return;
        }
        mc.ingameGUI.getChatGUI()
            .addToSentMessages(message);
        Ask ask = new Ask();
        ask.text = message;
        ask.context = context;
        DaveNetwork.sendToServer(ask);
    }
}
