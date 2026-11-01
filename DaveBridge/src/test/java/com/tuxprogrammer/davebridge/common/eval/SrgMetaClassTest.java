package com.tuxprogrammer.davebridge.common.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.Arrays;
import java.util.HashMap;

import net.minecraft.nbt.NBTTagCompound;

import org.junit.jupiter.api.Test;

import groovy.lang.Binding;
import groovy.lang.GroovyShell;
import groovy.lang.GroovySystem;
import groovy.lang.MetaClassRegistry;

class SrgMetaClassTest {

    /** Stands in for a mod tile entity whose members can't be listed on a dedicated server. */
    public static class UnlistableTile extends NBTTagCompound {
    }

    @Test
    void callsOnAClassBuiltFromItsAncestorDoNotRecurse() {
        MetaClassRegistry registry = GroovySystem.getMetaClassRegistry();
        MetaClassRegistry.MetaClassCreationHandle before = registry.getMetaClassCreationHandler();
        java.util.function.Function<Class<?>, Class<?>> resolver = SrgMetaClass.ancestorOf;
        try {
            SrgMetaClass.ancestorOf = c -> c == UnlistableTile.class ? NBTTagCompound.class : c;
            registry.setMetaClassCreationHandle(new SrgMetaClass.Handle(new SrgNames(new HashMap<>())));
            registry.removeMetaClass(UnlistableTile.class);
            Binding b = new Binding();
            b.setVariable("te", new UnlistableTile());
            Object out = new GroovyShell(b)
                .evaluate("def c = te.getClass(); [c.getName(), c.toString(), c.simpleName, c.name, te.hasNoTags()]");
            assertEquals(
                Arrays.asList(
                    UnlistableTile.class.getName(),
                    UnlistableTile.class.toString(),
                    "UnlistableTile",
                    UnlistableTile.class.getName(),
                    true),
                out);
        } finally {
            SrgMetaClass.ancestorOf = resolver;
            registry.setMetaClassCreationHandle(before);
            registry.removeMetaClass(UnlistableTile.class);
        }
    }
}
