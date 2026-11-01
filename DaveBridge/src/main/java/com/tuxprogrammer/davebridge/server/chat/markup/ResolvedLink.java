package com.tuxprogrammer.davebridge.server.chat.markup;

import java.util.Collections;
import java.util.List;

import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.util.IChatComponent;

/**
 * A token turned into chat components. Two variants because the click can differ for players with and without the
 * DaveBridge client half; most tokens use the same component for both.
 */
public final class ResolvedLink {

    /** Something that must reach a recipient before the chat line, e.g. NEI's bookmark payload packet. */
    public interface RecipientAction {

        void apply(EntityPlayerMP player);
    }

    public final IChatComponent vanilla;
    public final IChatComponent mod;
    /**
     * Must not share its chat line with other links: BetterQuesting rewrites the whole line that carries a quest link
     * into one text component, keeping only the formatting of the surrounding text.
     */
    public final boolean ownLine;
    public final List<RecipientAction> actions;

    public ResolvedLink(IChatComponent vanilla, IChatComponent mod, boolean ownLine, List<RecipientAction> actions) {
        this.vanilla = vanilla;
        this.mod = mod == null ? vanilla : mod;
        this.ownLine = ownLine;
        this.actions = actions == null ? Collections.<RecipientAction>emptyList() : actions;
    }

    public static ResolvedLink same(IChatComponent component) {
        return new ResolvedLink(component, component, false, null);
    }
}
