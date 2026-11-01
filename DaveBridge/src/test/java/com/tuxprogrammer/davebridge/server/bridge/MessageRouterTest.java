package com.tuxprogrammer.davebridge.server.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

import com.google.gson.JsonObject;

/** PROTOCOL.md 1.7: what counts as bad_json, and which reqId an error can still echo. */
class MessageRouterTest {

    private static ProtocolException parseFails(String raw) {
        return assertThrows(ProtocolException.class, () -> MessageRouter.parse(raw));
    }

    @Test
    void acceptsAnObjectWithAStringType() throws ProtocolException {
        JsonObject obj = MessageRouter.parse("{\"type\":\"ping\",\"reqId\":1,\"extra\":true}");
        assertEquals(
            "ping",
            obj.get("type")
                .getAsString());
    }

    @Test
    void malformedJsonIsBadJsonWithoutReqId() {
        ProtocolException e = parseFails("{\"type\":");
        assertEquals(Protocol.ERR_BAD_JSON, e.code());
        assertNull(e.reqId());
    }

    @Test
    void nonObjectsAreBadJson() {
        assertEquals(Protocol.ERR_BAD_JSON, parseFails("[]").code());
        assertEquals(Protocol.ERR_BAD_JSON, parseFails("\"say\"").code());
        assertEquals(Protocol.ERR_BAD_JSON, parseFails("").code());
    }

    @Test
    void missingOrNonStringTypeIsBadJsonAndKeepsReqId() {
        ProtocolException missing = parseFails("{\"reqId\":7}");
        assertEquals(Protocol.ERR_BAD_JSON, missing.code());
        assertEquals(
            7,
            missing.reqId()
                .getAsInt());

        ProtocolException number = parseFails("{\"type\":5,\"reqId\":\"r\"}");
        assertEquals(Protocol.ERR_BAD_JSON, number.code());
        assertEquals(
            "r",
            number.reqId()
                .getAsString());

        ProtocolException object = parseFails("{\"type\":{},\"reqId\":null}");
        assertEquals(Protocol.ERR_BAD_JSON, object.code());
        assertNull(object.reqId());
    }
}
