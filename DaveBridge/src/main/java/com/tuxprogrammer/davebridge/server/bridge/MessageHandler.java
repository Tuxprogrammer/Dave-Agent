package com.tuxprogrammer.davebridge.server.bridge;

/**
 * Handles one inbound message type. Called on a socket thread: validate here, then use
 * {@link MessageRouter#runOnMainThread} for anything that touches the game.
 */
public interface MessageHandler {

    void handle(Request request) throws ProtocolException;
}
