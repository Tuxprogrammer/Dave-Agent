package com.tuxprogrammer.davebridge.client;

import net.minecraft.client.gui.GuiScreen;
import net.minecraftforge.common.config.ConfigElement;

import com.tuxprogrammer.davebridge.DaveBridge;

import cpw.mods.fml.client.config.GuiConfig;

/** Mods &gt; DaveBridge &gt; Config: the client options. Changes are applied by {@link ClientEventHandler}. */
public class GuiDaveBridgeConfig extends GuiConfig {

    @SuppressWarnings({ "unchecked", "rawtypes" })
    public GuiDaveBridgeConfig(GuiScreen parent) {
        super(
            parent,
            new ConfigElement(ClientConfig.config.getCategory(ClientConfig.CATEGORY_CLIENT)).getChildElements(),
            DaveBridge.MODID,
            false,
            false,
            "DaveBridge");
    }
}
