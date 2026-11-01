package com.tuxprogrammer.davebridge.server.chat.markup;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import org.junit.jupiter.api.Test;

/**
 * OreDictionary cannot initialize outside a real game (its static init registers vanilla recipes), so this checks the
 * compiled class instead: Forge's {@code getOres(String)} and {@code getOreID(String)} create any unknown ore name, and
 * the ore lookup must use the non-creating {@code getOres(String, boolean)}.
 */
class MinecraftObjectsTest {

    @Test
    void oreLookupNeverCreatesOreNames() throws IOException {
        Path file = Paths.get(
            "build",
            "classes",
            "java",
            "main",
            "com",
            "tuxprogrammer",
            "davebridge",
            "server",
            "chat",
            "markup",
            "MinecraftObjects.class");
        assertTrue(Files.isRegularFile(file), "compiled class not found at " + file.toAbsolutePath());
        String bytes = new String(Files.readAllBytes(file), StandardCharsets.ISO_8859_1);
        assertTrue(bytes.contains("net/minecraftforge/oredict/OreDictionary"));
        // descriptors of the creating overloads: getOres(String) -> ArrayList, getOreID(String) -> int
        assertFalse(bytes.contains("(Ljava/lang/String;)Ljava/util/ArrayList;"), "uses getOres(String)");
        assertFalse(bytes.contains("getOreID"), "uses getOreID");
        assertTrue(bytes.contains("(Ljava/lang/String;Z)Ljava/util/List;"), "expected getOres(String, false)");
    }
}
