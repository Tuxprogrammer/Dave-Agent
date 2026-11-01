package com.tuxprogrammer.davebridge.common.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.google.gson.JsonElement;

class JsonDumpTest {

    private static JsonDump.Limits small() {
        return new JsonDump.Limits(3, 5, 20, 2000);
    }

    @Test
    void primitivesAndCollections() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("n", 1);
        m.put("d", Double.NaN);
        m.put("s", "hi");
        m.put("arr", new int[] { 1, 2 });
        m.put("list", Arrays.asList(true, null));
        m.put("cls", String.class);
        JsonDump d = new JsonDump(new JsonDump.Limits());
        assertEquals(
            "{\"n\":1,\"d\":\"NaN\",\"s\":\"hi\",\"arr\":[1,2],\"list\":[true,null],\"cls\":\"java.lang.String\"}",
            d.toJson(m)
                .toString());
        assertFalse(d.truncated());
    }

    @Test
    void capsItemsStringsAndDepth() {
        List<Integer> many = new ArrayList<>();
        for (int i = 0; i < 50; i++) many.add(i);
        JsonDump d = new JsonDump(small());
        JsonElement e = d.toJson(many);
        assertEquals(
            6,
            e.getAsJsonArray()
                .size());
        assertTrue(d.truncated());

        String clipped = JsonDump.dump(new String(new char[100]).replace('\0', 'x'), small())
            .getAsString();
        assertTrue(clipped.startsWith("xxxxxxxxxxxxxxxxxxxx...("), clipped);

        Object deep = Arrays.asList(Arrays.asList(Arrays.asList(Arrays.asList(Arrays.asList(1)))));
        String s = JsonDump.dump(deep, small())
            .toString();
        assertTrue(s.contains("$class"), s);
    }

    @Test
    void cyclesDoNotLoop() {
        Map<String, Object> a = new HashMap<>();
        a.put("self", a);
        String s = JsonDump.dump(a, new JsonDump.Limits())
            .toString();
        assertTrue(s.contains("<cycle"), s);
    }

    @Test
    void overallBudgetHolds() {
        List<String> big = new ArrayList<>();
        for (int i = 0; i < 10000; i++) big.add("0123456789012345678901234567890123456789");
        JsonDump.Limits l = new JsonDump.Limits(8, 100000, 4000, 5000);
        JsonDump d = new JsonDump(l);
        String s = d.toJson(big)
            .toString();
        assertTrue(s.length() < 8000, "length " + s.length());
        assertTrue(d.truncated());
    }

    @Test
    void unknownObjectsAndBrokenToString() {
        Object weird = new Object() {

            @Override
            public String toString() {
                throw new IllegalStateException("nope");
            }
        };
        String s = JsonDump.dump(weird, new JsonDump.Limits())
            .toString();
        assertTrue(s.contains("$class") && s.contains("toString failed"), s);
    }
}
