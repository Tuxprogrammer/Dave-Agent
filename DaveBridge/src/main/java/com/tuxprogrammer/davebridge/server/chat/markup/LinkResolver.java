package com.tuxprogrammer.davebridge.server.chat.markup;

import java.util.List;

/** Turns a markup token into chat components. Called on the server thread. */
public interface LinkResolver {

    /**
     * @return the resolved link, or null if the token cannot be resolved (the renderer then falls back to plain text);
     *         add a human-readable reason to {@code warnings} either way something was degraded
     */
    ResolvedLink resolve(Markup.Token token, List<String> warnings);
}
