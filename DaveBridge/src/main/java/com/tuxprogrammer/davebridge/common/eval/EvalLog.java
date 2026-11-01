package com.tuxprogrammer.davebridge.common.eval;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

/** The eval engine's logger: the mod's log4j logger, looked up here so the engine needs no Forge classes. */
final class EvalLog {

    private static final Logger LOG = LogManager.getLogger("davebridge");

    private EvalLog() {}

    static void warn(String message) {
        LOG.warn(message);
    }

    static void info(String message) {
        LOG.info(message);
    }

    static void debug(String message, Throwable t) {
        LOG.debug(message, t);
    }
}
