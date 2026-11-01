package com.tuxprogrammer.davebridge.common.eval;

import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

import org.codehaus.groovy.control.CompilationFailedException;
import org.codehaus.groovy.control.CompilerConfiguration;
import org.codehaus.groovy.control.customizers.ImportCustomizer;
import org.codehaus.groovy.runtime.InvokerHelper;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;

import groovy.lang.Binding;
import groovy.lang.GroovyClassLoader;
import groovy.lang.GroovyCodeSource;
import groovy.lang.Script;

/**
 * Compiles and runs Groovy scripts for live eval. Side-agnostic (no client or server classes), so the server and the
 * client half share it.
 * <p>
 * Compiling is slow (the first script loads Groovy itself, about a second), so {@link #compileAsync} runs it on a
 * background thread. Running is fast and must happen on the game's main thread (the caller queues it): the script
 * then sees a consistent world. Every run has a time limit, enforced by checks {@link ScriptChecks} compiles into
 * the script; its result is converted by {@link JsonDump} within size limits, and nothing it throws escapes
 * {@link #run}.
 */
public final class ScriptEngine {

    /** Star imports every script gets, so short scripts need no import lines. All are common (both sides) classes. */
    static final String[] STAR_IMPORTS = { "net.minecraft.block", "net.minecraft.entity", "net.minecraft.entity.player",
        "net.minecraft.init", "net.minecraft.inventory", "net.minecraft.item", "net.minecraft.nbt",
        "net.minecraft.server", "net.minecraft.tileentity", "net.minecraft.util", "net.minecraft.world",
        "net.minecraftforge.common.util", "net.minecraftforge.fluids", "net.minecraftforge.oredict" };

    private static final int CACHE_SIZE = 64;
    private static final AtomicInteger SCRIPT_IDS = new AtomicInteger();
    private static final ScriptEngine SHARED = new ScriptEngine(ScriptEngine.class.getClassLoader());

    private final ClassLoader parent;
    private final ExecutorService compiler = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "DaveBridge-eval-compiler");
        t.setDaemon(true);
        return t;
    });
    private final Map<String, Compiled> cache = Collections
        .synchronizedMap(new LinkedHashMap<String, Compiled>(16, 0.75f, true) {

            private static final long serialVersionUID = 1L;

            @Override
            protected boolean removeEldestEntry(Map.Entry<String, Compiled> eldest) {
                return size() > CACHE_SIZE;
            }
        });

    public ScriptEngine(ClassLoader parent) {
        this.parent = parent;
    }

    /** The engine for this JVM, loading script classes through the mod's own class loader. */
    public static ScriptEngine shared() {
        return SHARED;
    }

    /** A compiled script, ready to run any number of times. */
    public static final class Compiled {

        final Class<? extends Script> type;
        /** World-changing calls the source mentions (see {@link ScriptChecks#MUTATORS}). */
        public final List<String> mutators;

        Compiled(Class<? extends Script> type, List<String> mutators) {
            this.type = type;
            this.mutators = mutators;
        }
    }

    /** The source did not compile, or uses a blocked call. The message says why and is safe to show. */
    public static final class CompileError extends Exception {

        private static final long serialVersionUID = 1L;
        public final String kind;

        CompileError(String kind, String message) {
            super(message);
            this.kind = kind;
        }
    }

    /** Compiles on the engine's background thread. The future fails with {@link CompileError}. */
    public CompletableFuture<Compiled> compileAsync(String source) {
        CompletableFuture<Compiled> future = new CompletableFuture<>();
        try {
            compiler.execute(() -> {
                try {
                    future.complete(compile(source));
                } catch (Throwable t) {
                    future.completeExceptionally(t);
                }
            });
        } catch (Throwable t) {
            future.completeExceptionally(t);
        }
        return future;
    }

    /** Compiles {@code source} on the calling thread (cached by source text). */
    public Compiled compile(String source) throws CompileError {
        Compiled cached = cache.get(source);
        if (cached != null) {
            return cached;
        }
        SrgMetaClass.install(SrgNames.get());
        CompilerConfiguration config = new CompilerConfiguration();
        ImportCustomizer imports = new ImportCustomizer();
        imports.addStarImports(STAR_IMPORTS);
        ScriptChecks checks = new ScriptChecks();
        config.addCompilationCustomizers(imports, checks);
        config.setDisabledGlobalASTTransformations(Collections.singleton("groovy.grape.GrabAnnotationTransformation"));
        String name = "DaveScript" + SCRIPT_IDS.incrementAndGet();
        Class<?> type;
        // A loader per script, never closed: the script's classes stay loadable while it runs, and the loader and its
        // classes can be collected once the cache drops the script.
        GroovyClassLoader loader = new GroovyClassLoader(parent, config);
        try {
            type = loader.parseClass(new GroovyCodeSource(source, name + ".groovy", "/groovy/script"), false);
        } catch (CompilationFailedException e) {
            throw new CompileError("compile", clip(e.getMessage(), 2000));
        } catch (RuntimeException | LinkageError e) {
            throw new CompileError("compile", clip(e.toString(), 2000));
        }
        if (!checks.blocked()
            .isEmpty()) {
            throw new CompileError(
                "blocked",
                "refused: the script uses " + String.join(", ", checks.blocked())
                    + ". These stop or freeze the server; there is no way to allow them.");
        }
        if (!Script.class.isAssignableFrom(type)) {
            throw new CompileError("compile", "the source defines a class, not a script: write statements instead");
        }
        @SuppressWarnings("unchecked")
        Compiled compiled = new Compiled((Class<? extends Script>) type, checks.mutators());
        cache.put(source, compiled);
        return compiled;
    }

    /**
     * Runs a compiled script on the calling thread (the game's main thread) and describes the outcome as JSON:
     * {@code ok}, {@code result}, {@code output}, {@code ms}, and on failure {@code error}, {@code errorType},
     * {@code line}, {@code stack}. Never throws.
     *
     * @param bindings  variables the script sees ({@code out} is added: what it prints)
     * @param timeoutMs the script's time limit
     * @param limits    size limits for the result
     * @param maxOutput characters of printed output kept
     */
    public JsonObject run(Compiled compiled, Map<String, Object> bindings, long timeoutMs, JsonDump.Limits limits,
        int maxOutput) {
        JsonObject reply = new JsonObject();
        CappedWriter output = new CappedWriter(maxOutput);
        PrintWriter out = new PrintWriter(output, true);
        Binding binding = new Binding();
        for (Map.Entry<String, Object> e : bindings.entrySet()) {
            binding.setVariable(e.getKey(), e.getValue());
        }
        binding.setVariable("out", out);
        long start = System.nanoTime();
        Object value = null;
        Throwable failure = null;
        Deadline.begin(timeoutMs);
        try {
            Script script = InvokerHelper.createScript(compiled.type, binding);
            value = script.run();
        } catch (Throwable t) {
            failure = t;
        } finally {
            Deadline.end();
        }
        double ms = (System.nanoTime() - start) / 1_000_000.0;
        reply.addProperty("ms", Math.round(ms * 100) / 100.0);
        if (failure != null) {
            describeFailure(reply, failure, compiled.type.getName());
        } else {
            JsonDump dump = new JsonDump(limits);
            JsonElement json;
            Deadline.begin(Math.max(timeoutMs, 1000));
            try {
                json = dump.toJson(value);
            } catch (Throwable t) {
                json = new JsonPrimitive("<result could not be converted: " + t + ">");
            } finally {
                Deadline.end();
            }
            reply.addProperty("ok", true);
            reply.add("result", json);
            if (dump.truncated()) {
                reply.addProperty("truncated", true);
            }
        }
        out.flush();
        String printed = output.toString();
        if (!printed.isEmpty()) {
            reply.addProperty("output", printed);
        }
        if (output.truncated()) {
            reply.addProperty("outputTruncated", true);
        }
        return reply;
    }

    static void describeFailure(JsonObject reply, Throwable failure, String scriptClass) {
        Throwable root = unwrap(failure);
        reply.addProperty("ok", false);
        reply.addProperty("errorType", root instanceof ScriptTimeout ? "timeout" : "exception");
        // Groovy is shaded: show its classes under their real names (groovy.lang.MissingPropertyException).
        reply.addProperty("error", clip(unshade(root.toString()), 2000));
        JsonArray stack = new JsonArray();
        int line = -1;
        int added = 0;
        for (StackTraceElement frame : root.getStackTrace()) {
            boolean scriptFrame = frame.getClassName()
                .startsWith(scriptClass);
            if (scriptFrame && line < 0) {
                line = frame.getLineNumber();
            }
            if (added < 12 && (scriptFrame || !isPlumbing(frame.getClassName()))) {
                stack.add(new JsonPrimitive(frame.toString()));
                added++;
            }
        }
        if (line > 0) {
            reply.addProperty("line", line);
        }
        reply.add("stack", stack);
    }

    /** Groovy and reflection frames that say nothing about where a script went wrong. */
    private static boolean isPlumbing(String cls) {
        return cls.contains("groovy.") || cls.startsWith("java.lang.reflect.")
            || cls.startsWith("jdk.internal.")
            || cls.startsWith("sun.reflect.")
            || cls.startsWith("java.lang.invoke.")
            || cls.startsWith(
                ScriptEngine.class.getPackage()
                    .getName());
    }

    private static Throwable unwrap(Throwable t) {
        Throwable cur = t;
        for (int i = 0; i < 8; i++) {
            Throwable cause = cur.getCause();
            boolean wrapper = cur instanceof java.lang.reflect.InvocationTargetException
                || cur instanceof java.lang.reflect.UndeclaredThrowableException
                || cur.getClass()
                    .getName()
                    .endsWith("InvokerInvocationException");
            if (cause == null || cause == cur || !wrapper) {
                break;
            }
            cur = cause;
        }
        return cur;
    }

    /** Removes the shading prefix from class names in a message. */
    static String unshade(String s) {
        return s == null ? null : s.replace("com.tuxprogrammer.davebridge.shadow.", "");
    }

    static String clip(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }

    /** Names of the variables scripts see, for documentation and errors. */
    public static List<String> describeBindings(Map<String, Object> bindings) {
        List<String> names = new ArrayList<>(bindings.keySet());
        names.add("out");
        Collections.sort(names);
        return names;
    }
}
