package com.tuxprogrammer.davebridge.common.protocol;

/** S-&gt;C: stop the lesson with {@link #id}, or whatever lesson is playing when {@code id} is null or empty. */
public class LessonStop extends DavePacket {

    public static final String KIND = "lesson_stop";

    public String id;

    @Override
    public String kind() {
        return KIND;
    }
}
