package com.tuxprogrammer.davebridge.common.protocol;

/**
 * C-&gt;S: a lesson ended on the client. The server relays it to the agent as a {@code lesson_status} event so Dave
 * knows whether the player watched to the end or stopped it.
 */
public class LessonStatus extends DavePacket {

    public static final String KIND = "lesson_status";

    public static final String STATE_FINISHED = "finished";
    public static final String STATE_STOPPED = "stopped";

    /** The player stopped it (chat button, key, {@code /davebridge stop}). */
    public static final String REASON_PLAYER = "player";
    /** The player walked too far from where the lesson takes place. */
    public static final String REASON_WALKED_AWAY = "walked_away";
    /** The player changed dimension. */
    public static final String REASON_DIMENSION = "dimension";
    /** A new lesson replaced this one. */
    public static final String REASON_REPLACED = "replaced";
    /** The agent sent {@code lesson_stop}. */
    public static final String REASON_AGENT = "agent";
    /** A looping lesson ran for the maximum play time. */
    public static final String REASON_TIMEOUT = "timeout";
    /** The client could not play it (nothing playable after its own checks, wrong dimension on arrival). */
    public static final String REASON_REJECTED = "rejected";
    /** A non-looping lesson played to the end ({@link #STATE_FINISHED}). */
    public static final String REASON_DONE = "done";

    public String id;
    public String state;
    public String reason;

    @Override
    public String kind() {
        return KIND;
    }
}
