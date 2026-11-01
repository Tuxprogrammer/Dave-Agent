package com.tuxprogrammer.davebridge.common.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import net.minecraft.davebridgetest.FakeSrgEntity;

import org.junit.jupiter.api.Test;

import com.google.gson.JsonObject;

/** The eval engine without a game: compile checks, time limits, failures, output and SRG name translation. */
class ScriptEngineTest {

    private final ScriptEngine engine = ScriptEngine.shared();

    private JsonObject run(String source, long timeoutMs, Map<String, Object> bindings) throws Exception {
        ScriptEngine.Compiled c = engine.compileAsync(source)
            .get(60, TimeUnit.SECONDS);
        return engine.run(c, bindings, timeoutMs, new JsonDump.Limits(), 1000);
    }

    private JsonObject run(String source) throws Exception {
        return run(source, 1000, new HashMap<>());
    }

    @Test
    void returnsJsonAndOutput() throws Exception {
        JsonObject r = run("println 'hello'; [a: 1, b: [1, 2, 3], c: 'x'.multiply(3)]");
        assertTrue(
            r.get("ok")
                .getAsBoolean(),
            r.toString());
        assertEquals(
            "{\"a\":1,\"b\":[1,2,3],\"c\":\"xxx\"}",
            r.get("result")
                .toString());
        assertEquals(
            "hello\n",
            r.get("output")
                .getAsString()
                .replace("\r", ""));
    }

    @Test
    void bindingsAreVisible() throws Exception {
        Map<String, Object> b = new HashMap<>();
        b.put("params", java.util.Collections.singletonMap("n", 4.0));
        JsonObject r = run("(params.n as int) * 2", 1000, b);
        assertEquals(
            8,
            r.get("result")
                .getAsInt());
    }

    @Test
    void infiniteLoopTimesOut() throws Exception {
        long start = System.nanoTime();
        JsonObject r = run("while (true) { }", 150, new HashMap<>());
        assertFalse(
            r.get("ok")
                .getAsBoolean());
        assertEquals(
            "timeout",
            r.get("errorType")
                .getAsString());
        assertTrue((System.nanoTime() - start) / 1_000_000 < 5000, "stopped promptly");
    }

    @Test
    void closureLoopAndMethodLoopTimeOut() throws Exception {
        assertEquals(
            "timeout",
            run("(1..Integer.MAX_VALUE).each { it * 2 }", 150, new HashMap<>()).get("errorType")
                .getAsString());
        assertEquals(
            "timeout",
            run("def spin() { for (;;) {} }\nspin()", 150, new HashMap<>()).get("errorType")
                .getAsString());
        // catching Exception does not swallow the timeout
        assertEquals(
            "timeout",
            run("while (true) { try { 1 + 1 } catch (Exception e) { } }", 150, new HashMap<>()).get("errorType")
                .getAsString());
    }

    @Test
    void exceptionsAreReportedWithLine() throws Exception {
        JsonObject r = run("def x = 1\nthrow new IllegalStateException('boom')");
        assertFalse(
            r.get("ok")
                .getAsBoolean());
        assertEquals(
            "exception",
            r.get("errorType")
                .getAsString());
        assertTrue(
            r.get("error")
                .getAsString()
                .contains("boom"));
        assertEquals(
            2,
            r.get("line")
                .getAsInt());
    }

    @Test
    void missingPropertyIsAnException() throws Exception {
        JsonObject r = run("nosuchvariable + 1");
        assertFalse(
            r.get("ok")
                .getAsBoolean());
        assertTrue(
            r.get("error")
                .getAsString()
                .contains("nosuchvariable"));
    }

    @Test
    void compileErrorsAndFootgunsAreRefused() {
        ScriptEngine.CompileError syntax = assertThrows(ScriptEngine.CompileError.class, () -> engine.compile("def ("));
        assertEquals("compile", syntax.kind);
        for (String bad : new String[] { "System.exit(0)", "Runtime.getRuntime().halt(1)", "Thread.sleep(1000)",
            "sleep(1000)", "server.initiateShutdown()", "server.executeCommand(server, 'stop')",
            "def o = new Object(); synchronized (o) { o.wait() }" }) {
            ScriptEngine.CompileError e = assertThrows(
                ScriptEngine.CompileError.class,
                () -> engine.compile(bad + "\n// " + System.nanoTime()),
                bad);
            assertEquals("blocked", e.kind, bad);
        }
    }

    @Test
    void worldChangesAreNoticed() throws Exception {
        ScriptEngine.Compiled c = engine.compile("world.setBlock(0, 64, 0, null)\nstack.stackSize = 0");
        assertTrue(c.mutators.contains("setBlock"), c.mutators.toString());
        assertTrue(c.mutators.contains("stackSize ="), c.mutators.toString());
        assertTrue(engine.compile("world.getBlock(0, 64, 0)").mutators.isEmpty());
    }

    @Test
    void mcpNamesReachSrgMembers() throws Exception {
        Map<String, Object> b = new HashMap<>();
        FakeSrgEntity e = new FakeSrgEntity();
        b.put("e", e);
        JsonObject r = run(
            "e.health = 5f\n[e.inventory, e.posX, e.getHealth(), e.health, e.exact(), e.@inventory, "
                + "net.minecraft.davebridgetest.FakeSrgEntity.stone]",
            1000,
            b);
        assertTrue(
            r.get("ok")
                .getAsBoolean(),
            r.toString());
        assertEquals(
            "[\"the inventory\",12.5,5.0,5.0,\"exact\",\"the inventory\",1]",
            r.get("result")
                .toString());
        assertEquals(5f, e.func_110143_aJ());
        JsonObject missing = run("e.noSuchThing", 1000, b);
        assertTrue(
            missing.get("error")
                .getAsString()
                .contains("noSuchThing"));
    }

    @Test
    void scriptsCannotOverrunWithOutput() throws Exception {
        JsonObject r = run("10000.times { println 'spam spam spam' }; 1");
        assertTrue(
            r.get("outputTruncated")
                .getAsBoolean());
        assertTrue(
            r.get("output")
                .getAsString()
                .length() <= 1000);
    }
}
