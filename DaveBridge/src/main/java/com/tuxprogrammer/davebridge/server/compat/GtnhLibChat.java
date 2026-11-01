package com.tuxprogrammer.davebridge.server.compat;

import net.minecraft.util.ChatComponentText;
import net.minecraft.util.IChatComponent;
import net.minecraftforge.fluids.FluidStack;

import cpw.mods.fml.common.Loader;

/**
 * GTNHLib's custom chat components, which serialize the stack and resolve the name on each client in the client's
 * language. Every GTNH client has GTNHLib (its IChatComponent serializer mixin understands {@code gtnhlib_id}).
 */
// Source:
// https://github.com/GTNewHorizons/GTNHLib/blob/0.11.54/src/main/java/com/gtnewhorizon/gtnhlib/chat/customcomponents/ChatComponentFluidName.java
// and .../mixins/early/MixinIChatComponentSerializer.java ({"gtnhlib_id": id, "gtnhlib_payload": {id: base64}}).
public final class GtnhLibChat {

    private static Boolean available;

    private GtnhLibChat() {}

    static boolean available() {
        if (available == null) {
            boolean ok = Loader.isModLoaded("gtnhlib");
            if (ok) {
                try {
                    Class.forName("com.gtnewhorizon.gtnhlib.chat.customcomponents.ChatComponentFluidName");
                } catch (Throwable t) {
                    ok = false;
                }
            }
            available = ok;
        }
        return available;
    }

    /** The fluid's name: GTNHLib's client-localized component if possible, else the server's localized text. */
    public static IChatComponent fluidName(FluidStack stack) {
        if (available()) {
            return Impl.fluidName(stack);
        }
        return new ChatComponentText(stack.getLocalizedName());
    }

    /** Kept separate so GTNHLib classes are only loaded when GTNHLib is present. */
    private static final class Impl {

        static IChatComponent fluidName(FluidStack stack) {
            return new com.gtnewhorizon.gtnhlib.chat.customcomponents.ChatComponentFluidName(stack);
        }
    }
}
