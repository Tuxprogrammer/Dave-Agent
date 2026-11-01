package com.tuxprogrammer.davebridge.common;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.File;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import cpw.mods.fml.relauncher.FMLInjectionData;
import cpw.mods.fml.relauncher.FMLRelaunchLog;
import cpw.mods.fml.relauncher.Side;

/**
 * Forge renames a config it cannot parse and starts from an empty one. Config must not let that replace the token or
 * reset bindAddress: it keeps the previous values and puts the file back.
 */
class ConfigReloadTest {

    private static final String VALID = "network {\n" + "    S:authToken=unit-test-token\n"
        + "    S:bindAddress=0.0.0.0\n"
        + "}\n";
    /** One closing brace too many: Forge throws "attempted to close too many categories". */
    private static final String BROKEN = VALID + "}\n";

    @TempDir
    Path dir;

    private String savedToken;
    private String savedBind;
    private boolean savedEnabled;
    private Object savedHome;
    private Object savedSide;

    @BeforeEach
    void setUp() throws Exception {
        savedToken = Config.authToken;
        savedBind = Config.bindAddress;
        savedEnabled = Config.enabled;
        Field home = FMLInjectionData.class.getDeclaredField("minecraftHome");
        home.setAccessible(true);
        savedHome = home.get(null);
        home.set(null, dir.toFile());
        // Forge's fallback logs through FMLLog, which needs the side set as it is in a running game.
        Field side = FMLRelaunchLog.class.getDeclaredField("side");
        side.setAccessible(true);
        savedSide = side.get(null);
        if (savedSide == null) {
            side.set(null, Side.SERVER);
        }
    }

    @AfterEach
    void tearDown() throws Exception {
        Config.authToken = savedToken;
        Config.bindAddress = savedBind;
        Config.enabled = savedEnabled;
        Field home = FMLInjectionData.class.getDeclaredField("minecraftHome");
        home.setAccessible(true);
        home.set(null, savedHome);
        Field side = FMLRelaunchLog.class.getDeclaredField("side");
        side.setAccessible(true);
        side.set(null, savedSide);
    }

    private static void write(File file, String text) throws Exception {
        Files.write(file.toPath(), text.getBytes(StandardCharsets.UTF_8));
    }

    private static String read(File file) throws Exception {
        return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
    }

    @Test
    void unparseableFileKeepsTokenAndBindAddress() throws Exception {
        File file = dir.resolve("davebridge.cfg")
            .toFile();
        write(file, VALID);
        Config.init(file);
        assertEquals("unit-test-token", Config.authToken);
        assertEquals("0.0.0.0", Config.bindAddress);

        write(file, BROKEN);
        assertFalse(Config.reload());
        assertEquals("unit-test-token", Config.authToken, "token must not be regenerated");
        assertEquals("0.0.0.0", Config.bindAddress);
        assertEquals(BROKEN, read(file), "the owner's file is put back so it can be fixed in place");
        String[] errored = dir.toFile()
            .list((d, name) -> name.startsWith("davebridge.cfg_") && name.endsWith(".errored"));
        assertEquals(1, errored.length, "Forge's own rename path was exercised");

        write(file, VALID);
        assertTrue(Config.reload());
        assertEquals("unit-test-token", Config.authToken);
    }

    @Test
    void emptyTokenIsGeneratedOnce() throws Exception {
        File file = dir.resolve("fresh.cfg")
            .toFile();
        Config.init(file);
        String generated = Config.authToken;
        assertEquals(48, generated.length());
        assertTrue(Config.reload());
        assertEquals(generated, Config.authToken, "a saved token is reused, not regenerated");
    }
}
