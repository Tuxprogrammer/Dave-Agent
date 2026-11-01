package com.tuxprogrammer.davebridge.common.eval;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * MCP and SRG member names of vanilla Minecraft and Forge.
 * <p>
 * Outside the dev environment, vanilla members have their SRG names at runtime ({@code field_71071_by}), while
 * class names and mod members keep their real names. Scripts are written with MCP names ({@code player.inventory}),
 * so {@link SrgMetaClass} translates a name it cannot find through this table. An MCP name can belong to several SRG
 * names (different classes); the caller tries each on the receiver, and only the right one exists there.
 * <p>
 * The table is {@code assets/davebridge/eval/srg-names.tsv}, generated at build time from the MCP mappings the build
 * itself uses (see {@code dependencies.gradle}). Immutable once loaded; thread-safe.
 */
public final class SrgNames {

    public static final String RESOURCE = "/assets/davebridge/eval/srg-names.tsv";

    private static volatile SrgNames instance;

    private final Map<String, String> srgToMcp;
    private final Map<String, List<String>> mcpToSrg;

    SrgNames(Map<String, String> srgToMcp) {
        this(srgToMcp, pairsOf(srgToMcp));
    }

    private static List<String[]> pairsOf(Map<String, String> map) {
        List<String[]> pairs = new ArrayList<>();
        for (Map.Entry<String, String> e : map.entrySet()) {
            pairs.add(new String[] { e.getKey(), e.getValue() });
        }
        return pairs;
    }

    /**
     * @param srgToMcp the name shown for each SRG name (the first one listed)
     * @param pairs    every (srg, name) pair: an SRG name may have an older and a newer MCP name, and both work
     */
    SrgNames(Map<String, String> srgToMcp, List<String[]> pairs) {
        this.srgToMcp = srgToMcp;
        Map<String, List<String>> reverse = new HashMap<>();
        for (String[] p : pairs) {
            List<String> list = reverse.computeIfAbsent(p[1], k -> new ArrayList<>(1));
            if (!list.contains(p[0])) {
                list.add(p[0]);
            }
        }
        for (Map.Entry<String, List<String>> e : reverse.entrySet()) {
            Collections.sort(e.getValue());
            e.setValue(Collections.unmodifiableList(e.getValue()));
        }
        this.mcpToSrg = reverse;
    }

    /** The table bundled in the jar (empty, with a log line, if it is missing). */
    public static SrgNames get() {
        SrgNames names = instance;
        if (names == null) {
            synchronized (SrgNames.class) {
                names = instance;
                if (names == null) {
                    names = loadBundled();
                    instance = names;
                }
            }
        }
        return names;
    }

    private static SrgNames loadBundled() {
        try (InputStream in = SrgNames.class.getResourceAsStream(RESOURCE)) {
            if (in == null) {
                EvalLog.warn("No " + RESOURCE + " in the jar: MCP names will not be translated");
                return new SrgNames(new HashMap<>());
            }
            return parse(new InputStreamReader(in, StandardCharsets.UTF_8));
        } catch (IOException e) {
            EvalLog.warn("Could not read " + RESOURCE + ": " + e);
            return new SrgNames(new HashMap<>());
        }
    }

    /**
     * Parses {@code srg<TAB>name} lines; {@code #} starts a comment line. An SRG name may appear more than once (an
     * older and a newer MCP name); the first is the one {@link #mcp} shows, all of them translate.
     */
    public static SrgNames parse(Reader reader) throws IOException {
        Map<String, String> map = new HashMap<>();
        List<String[]> pairs = new ArrayList<>();
        BufferedReader br = new BufferedReader(reader);
        String line;
        while ((line = br.readLine()) != null) {
            if (line.isEmpty() || line.charAt(0) == '#') {
                continue;
            }
            int tab = line.indexOf('\t');
            if (tab <= 0 || tab == line.length() - 1) {
                continue;
            }
            String srg = line.substring(0, tab);
            String name = line.substring(tab + 1);
            map.putIfAbsent(srg, name);
            pairs.add(new String[] { srg, name });
        }
        return new SrgNames(map, pairs);
    }

    /** True for names that look like SRG member names ({@code field_123_a}, {@code func_123_a}). */
    public static boolean isSrg(String name) {
        return name != null && (name.startsWith("field_") || name.startsWith("func_"));
    }

    /** The MCP name for an SRG name, or null if unknown. */
    public String mcp(String srg) {
        return srgToMcp.get(srg);
    }

    /** {@code name} with an SRG name replaced by its MCP name (other names unchanged). */
    public String readable(String name) {
        String mcp = isSrg(name) ? srgToMcp.get(name) : null;
        return mcp != null ? mcp : name;
    }

    /** Every SRG name that has this MCP name, field and method names alike (empty if none). */
    public List<String> srg(String mcp) {
        List<String> list = mcpToSrg.get(mcp);
        return list == null ? Collections.emptyList() : list;
    }

    /** SRG field names ({@code field_*}) for an MCP name. */
    public List<String> srgFields(String mcp) {
        return filter(srg(mcp), "field_");
    }

    /** SRG method names ({@code func_*}) for an MCP name. */
    public List<String> srgMethods(String mcp) {
        return filter(srg(mcp), "func_");
    }

    private static List<String> filter(List<String> names, String prefix) {
        if (names.isEmpty()) {
            return names;
        }
        List<String> out = new ArrayList<>(names.size());
        for (String n : names) {
            if (n.startsWith(prefix)) {
                out.add(n);
            }
        }
        return out;
    }

    public int size() {
        return srgToMcp.size();
    }
}
