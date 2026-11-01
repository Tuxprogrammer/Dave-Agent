package com.tuxprogrammer.davebridge.client;

import java.util.Set;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiScreen;

import cpw.mods.fml.client.IModGuiFactory;

/** Enables the Config button in the Mods list. Named as a string in {@code @Mod}, so a server never loads it. */
public class GuiFactory implements IModGuiFactory {

    @Override
    public void initialize(Minecraft mc) {}

    @Override
    public Class<? extends GuiScreen> mainConfigGuiClass() {
        return GuiDaveBridgeConfig.class;
    }

    @Override
    public Set<RuntimeOptionCategoryElement> runtimeGuiCategories() {
        return null;
    }

    @Override
    public RuntimeOptionGuiHandler getHandlerFor(RuntimeOptionCategoryElement element) {
        return null;
    }
}
