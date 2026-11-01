package com.tuxprogrammer.davebridge.server.lesson;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.google.gson.JsonObject;
import com.tuxprogrammer.davebridge.common.protocol.DavePackets;
import com.tuxprogrammer.davebridge.common.protocol.LessonStatus;
import com.tuxprogrammer.davebridge.server.ClientModTracker;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;
import com.tuxprogrammer.davebridge.server.bridge.ProtocolException;

class LessonServiceTest {

    @Test
    void anAbsentPlayerIsNotFound() {
        // No server in unit tests, so nobody is online. DaveChat.resolveTargets returns nobody for an absent name
        // (a say only warns); a lesson must answer not_found, not fail with an internal error.
        ProtocolException e = assertThrows(ProtocolException.class, () -> LessonService.lessonPlayer("Nobody"));
        assertEquals(Protocol.ERR_NOT_FOUND, e.code());
        assertEquals(
            Protocol.ERR_BAD_REQUEST,
            assertThrows(ProtocolException.class, () -> LessonService.lessonPlayer("@a")).code());
    }

    @Test
    void lessonsNeedTheCapabilityAndOurProtocol() {
        ClientModTracker tracker = new ClientModTracker();
        UUID a = UUID.randomUUID(), b = UUID.randomUUID(), c = UUID.randomUUID();
        tracker.put(a, "0.2.0", DavePackets.PROTOCOL_VERSION, new String[] { "render", "lesson" }, false);
        tracker.put(b, "0.1.0", DavePackets.PROTOCOL_VERSION, new String[] { "render", "ask" }, false);
        tracker.put(c, "9.0.0", DavePackets.PROTOCOL_VERSION + 1, new String[] { "lesson" }, false);
        assertTrue(LessonService.canPlayLessons(tracker.get(a)));
        // No clientEvalAllowed needed: lessons are data.
        assertFalse(tracker.get(a).clientEvalAllowed);
        assertFalse(LessonService.canPlayLessons(tracker.get(b)), "older client half without lessons");
        assertFalse(LessonService.canPlayLessons(tracker.get(c)), "other protocol");
        assertFalse(LessonService.canPlayLessons(null), "no client half");
    }

    @Test
    void statusEventKeepsKnownFieldsOnly() {
        LessonStatus s = new LessonStatus();
        s.id = "ebf";
        s.state = LessonStatus.STATE_STOPPED;
        s.reason = LessonStatus.REASON_WALKED_AWAY;
        JsonObject e = LessonService.statusEvent(s);
        assertEquals(
            "lesson_status",
            e.get("type")
                .getAsString());
        assertEquals(
            "ebf",
            e.get("id")
                .getAsString());
        assertEquals(
            "stopped",
            e.get("state")
                .getAsString());
        assertEquals(
            "walked_away",
            e.get("reason")
                .getAsString());

        s.reason = "<script>";
        assertEquals(
            "other",
            LessonService.statusEvent(s)
                .get("reason")
                .getAsString());
        s.id = new String(new char[500]).replace('\0', 'x');
        assertEquals(
            LessonService.MAX_STATUS_FIELD,
            LessonService.statusEvent(s)
                .get("id")
                .getAsString()
                .length());
        s.state = "exploded";
        assertNull(LessonService.statusEvent(s));
        s.state = null;
        assertNull(LessonService.statusEvent(s));
        assertNull(LessonService.statusEvent(null));
    }
}
