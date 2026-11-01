package com.tuxprogrammer.davebridge.structure;

import static org.junit.jupiter.api.Assertions.assertTrue;

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
 * Static side-safety check over compiled classes: nothing outside the {@code client} package may reference a client
 * class (vanilla client, LWJGL, or our own client package), or a dedicated server would crash loading it. Class
 * references appear in the constant pool in internal (slash) form, so a byte search is enough; the
 * {@code @SidedProxy} class name is a dotted string and is not matched.
 */
class SideSafetyTest {

    private static final String[] FORBIDDEN = { "net/minecraft/client/", "org/lwjgl/",
        "com/tuxprogrammer/davebridge/client/" };

    @Test
    void commonAndServerClassesDoNotReferenceClientClasses() throws IOException {
        Path root = Paths.get("build", "classes", "java", "main", "com", "tuxprogrammer", "davebridge");
        assertTrue(Files.isDirectory(root), "compiled classes not found at " + root.toAbsolutePath());
        List<String> violations = new ArrayList<>();
        int checked = 0;
        try (Stream<Path> files = Files.walk(root)) {
            for (Path file : (Iterable<Path>) files::iterator) {
                String rel = root.relativize(file)
                    .toString()
                    .replace('\\', '/');
                if (!rel.endsWith(".class") || rel.startsWith("client/")) {
                    continue;
                }
                checked++;
                String bytes = new String(Files.readAllBytes(file), StandardCharsets.ISO_8859_1);
                for (String bad : FORBIDDEN) {
                    if (bytes.contains(bad)) {
                        violations.add(rel + " -> " + bad);
                    }
                }
            }
        }
        assertTrue(checked > 10, "expected to check the common/server classes, checked " + checked);
        assertTrue(violations.isEmpty(), "client references outside the client package: " + violations);
    }
}
