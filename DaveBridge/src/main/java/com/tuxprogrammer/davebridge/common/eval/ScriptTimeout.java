package com.tuxprogrammer.davebridge.common.eval;

/**
 * Thrown inside a script when its time is up. An {@link Error}, so a script's {@code catch (Exception e)} does not
 * swallow it; a script that catches {@code Throwable} still hits the next check at its next loop iteration.
 */
public final class ScriptTimeout extends Error {

    private static final long serialVersionUID = 1L;

    public ScriptTimeout(long millis) {
        super("script ran longer than " + millis + " ms and was stopped", null, false, false);
    }
}
