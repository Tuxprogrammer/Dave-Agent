package com.tuxprogrammer.davebridge.client;

import java.io.File;
import java.util.Arrays;

import net.minecraftforge.common.config.Configuration;
import net.minecraftforge.common.config.Property;

/**
 * Client-only options ({@code config/davebridge-client.cfg}). Never created on a dedicated server. Editable in game
 * from Mods &gt; DaveBridge &gt; Config ({@link GuiDaveBridgeConfig}) and, for the opt-in, with
 * {@code /davebridge optin|optout}.
 */
public final class ClientConfig {

    public static final String CATEGORY_CLIENT = "client";

    public static volatile boolean clientEvalAllowed = false;
    public static volatile boolean optInReminder = true;
    public static volatile String askPrefix = "dave, ";

    static Configuration config;

    private ClientConfig() {}

    public static void init(File file) {
        config = new Configuration(file);
        config.load();
        sync();
    }

    /** Reads every option from {@link #config}, after loading or after the config screen, and saves new defaults. */
    static void sync() {
        config.setCategoryComment(CATEGORY_CLIENT, "DaveBridge client options. The client half is optional.");
        config.setCategoryLanguageKey(CATEGORY_CLIENT, "davebridge.config.client");
        Property eval = config.get(
            CATEGORY_CLIENT,
            "clientEvalAllowed",
            false,
            "Allow Dave (via the server) to run code on THIS computer, so he can see and change things in your game. "
                + "Only turn it on for servers you trust. Same as /davebridge optin and /davebridge optout.");
        eval.setLanguageKey("davebridge.config.clientEvalAllowed");
        Property remind = config.get(
            CATEGORY_CLIENT,
            "optInReminder",
            true,
            "Remind me about the opt-in when I join a server that runs Dave. /davebridge optout turns it off.");
        remind.setLanguageKey("davebridge.config.optInReminder");
        Property prefix = config.get(
            CATEGORY_CLIENT,
            "askPrefix",
            "dave, ",
            "Text pre-filled in the chat line opened by the 'Ask Dave' key.");
        prefix.setLanguageKey("davebridge.config.askPrefix");
        config.getCategory(CATEGORY_CLIENT)
            .setPropertyOrder(Arrays.asList("clientEvalAllowed", "optInReminder", "askPrefix"));

        clientEvalAllowed = eval.getBoolean(false);
        optInReminder = remind.getBoolean(true);
        askPrefix = prefix.getString();
        if (config.hasChanged()) {
            config.save();
        }
    }

    /** Saves an opt-in choice. Opting out also stops the join reminder: the player has answered. */
    static void setClientEvalAllowed(boolean allowed) {
        config.get(CATEGORY_CLIENT, "clientEvalAllowed", false)
            .set(allowed);
        if (!allowed) {
            config.get(CATEGORY_CLIENT, "optInReminder", true)
                .set(false);
        }
        config.save();
        sync();
    }
}
