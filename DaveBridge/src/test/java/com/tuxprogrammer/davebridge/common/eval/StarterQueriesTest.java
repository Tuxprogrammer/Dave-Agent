package com.tuxprogrammer.davebridge.common.eval;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

import org.junit.jupiter.api.Test;

/**
 * The daemon ships starter queries in {@code dave/queries/} (outside this project). Each must compile with the
 * engine's settings, use no blocked call, and be read-only if it says {@code @mode: read}. Skipped when the folder is
 * not next to DaveBridge (a standalone checkout of the mod).
 */
class StarterQueriesTest {

    @Test
    void starterQueriesCompile() throws IOException {
        Path dir = Paths.get("..", "dave", "queries");
        assumeTrue(Files.isDirectory(dir), "no dave/queries next to DaveBridge");
        List<String> problems = new ArrayList<>();
        int n = 0;
        try (Stream<Path> files = Files.list(dir)) {
            for (Path p : (Iterable<Path>) files.filter(
                f -> f.toString()
                    .endsWith(".groovy"))::iterator) {
                n++;
                String src = new String(Files.readAllBytes(p), StandardCharsets.UTF_8);
                try {
                    ScriptEngine.Compiled c = ScriptEngine.shared()
                        .compile(src);
                    if (src.contains("// @mode: read") && !c.mutators.isEmpty()) {
                        problems.add(p.getFileName() + " is read mode but calls " + c.mutators);
                    }
                } catch (ScriptEngine.CompileError e) {
                    problems.add(p.getFileName() + ": " + e.kind + ": " + e.getMessage());
                }
            }
        }
        assertTrue(n >= 5, "expected the starter set, found " + n);
        assertTrue(problems.isEmpty(), String.join("\n", problems));
    }
}
