package com.tuxprogrammer.davebridge.common.eval;

import java.io.Writer;

/** Collects a script's printed output up to a character cap; the rest is dropped and {@link #truncated()} is set. */
public final class CappedWriter extends Writer {

    private final StringBuilder sb = new StringBuilder();
    private final int max;
    private boolean truncated;

    public CappedWriter(int max) {
        this.max = max;
    }

    @Override
    public void write(char[] cbuf, int off, int len) {
        int room = max - sb.length();
        if (room <= 0) {
            truncated |= len > 0;
            return;
        }
        if (len > room) {
            truncated = true;
            len = room;
        }
        sb.append(cbuf, off, len);
    }

    @Override
    public void flush() {}

    @Override
    public void close() {}

    public boolean truncated() {
        return truncated;
    }

    @Override
    public String toString() {
        return sb.toString();
    }
}
