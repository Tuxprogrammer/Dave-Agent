package com.tuxprogrammer.davebridge.common.eval;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

import org.codehaus.groovy.ast.ClassCodeVisitorSupport;
import org.codehaus.groovy.ast.ClassHelper;
import org.codehaus.groovy.ast.ClassNode;
import org.codehaus.groovy.ast.MethodNode;
import org.codehaus.groovy.ast.VariableScope;
import org.codehaus.groovy.ast.expr.ArgumentListExpression;
import org.codehaus.groovy.ast.expr.BinaryExpression;
import org.codehaus.groovy.ast.expr.ClosureExpression;
import org.codehaus.groovy.ast.expr.ConstantExpression;
import org.codehaus.groovy.ast.expr.Expression;
import org.codehaus.groovy.ast.expr.MethodCallExpression;
import org.codehaus.groovy.ast.expr.PropertyExpression;
import org.codehaus.groovy.ast.expr.StaticMethodCallExpression;
import org.codehaus.groovy.ast.expr.TupleExpression;
import org.codehaus.groovy.ast.stmt.BlockStatement;
import org.codehaus.groovy.ast.stmt.DoWhileStatement;
import org.codehaus.groovy.ast.stmt.ExpressionStatement;
import org.codehaus.groovy.ast.stmt.ForStatement;
import org.codehaus.groovy.ast.stmt.Statement;
import org.codehaus.groovy.ast.stmt.WhileStatement;
import org.codehaus.groovy.classgen.GeneratorContext;
import org.codehaus.groovy.control.CompilePhase;
import org.codehaus.groovy.control.SourceUnit;
import org.codehaus.groovy.control.customizers.CompilationCustomizer;

/**
 * Compile-time pass over every script (one instance per compilation):
 * <ul>
 * <li>inserts {@link Deadline#check()} at the start of every method, closure and loop body, so time limits work;</li>
 * <li>finds calls to obvious footguns (server stop, {@code System.exit}, {@code sleep}, ...): the script is refused;
 * </li>
 * <li>notes calls that look like world changes ({@code setBlock}, {@code setInventorySlotContents}, ...), so a
 * read-only request can be told to use write mode and get the player's confirmation.</li>
 * </ul>
 * These are accident guards, not security: Groovy is dynamic and a determined script can always get around a name
 * check. The trust model (PROTOCOL.md) accepts that.
 */
public final class ScriptChecks extends CompilationCustomizer {

    /** Method names never allowed: they stop or freeze the server. MCP and SRG names. */
    static final Set<String> BLOCKED = new HashSet<>(
        Arrays.asList(
            "exit",
            "halt",
            "initiateShutdown",
            "func_71263_m",
            "stopServer",
            "func_71260_j",
            "sleep",
            "wait",
            "suspend",
            "stop"));

    /** Calls that change the world, inventories or entities. MCP and SRG names. */
    static final Set<String> MUTATORS = new HashSet<>(
        Arrays.asList(
            "setBlock",
            "func_147449_b",
            "func_147465_d",
            "setBlockToAir",
            "func_147468_f",
            "setBlockMetadataWithNotify",
            "func_72921_c",
            "setTileEntity",
            "func_147455_a",
            "removeTileEntity",
            "func_147475_p",
            "func_147480_a",
            "setInventorySlotContents",
            "func_70299_a",
            "decrStackSize",
            "func_70298_a",
            "addItemStackToInventory",
            "func_70441_a",
            "consumeInventoryItem",
            "func_146026_a",
            "setDead",
            "func_70106_y",
            "spawnEntityInWorld",
            "func_72838_d",
            "createExplosion",
            "func_72876_a",
            "newExplosion",
            "func_72885_a",
            "executeCommand",
            "func_71556_a",
            "setPositionAndUpdate",
            "func_70634_a",
            "travelToDimension",
            "func_71027_c",
            "setHealth",
            "func_70606_j",
            "attackEntityFrom",
            "func_70097_a",
            "setFire",
            "func_70015_d",
            "dropItem",
            "func_145779_a",
            "entityDropItem",
            "func_70099_a",
            "addPotionEffect",
            "func_70690_d",
            "setGameType",
            "func_71033_a",
            "setWorldTime",
            "func_72877_b",
            "setSpawnLocation",
            "func_72950_A",
            "setStoredEU",
            "increaseStoredEnergyUnits",
            "decreaseStoredEnergyUnits",
            "doExplosion",
            "setItemStack"));

    /** Property assignments that change things ({@code stack.stackSize = 0}). */
    static final Set<String> MUTATOR_PROPERTIES = new HashSet<>(
        Arrays.asList("stackSize", "field_77994_a", "mItemCount", "mItemStack", "isDead", "field_70128_L"));

    private static final Pattern STOP_COMMAND = Pattern.compile("^\\s*/?\\s*(stop|restart|halt)\\b.*", Pattern.DOTALL);
    private static final Set<String> COMMAND_CALLS = new HashSet<>(Arrays.asList("executeCommand", "func_71556_a"));

    private final Set<String> blocked = new LinkedHashSet<>();
    private final Set<String> mutators = new LinkedHashSet<>();

    public ScriptChecks() {
        super(CompilePhase.CANONICALIZATION);
    }

    /** Footguns found: the script must not run. Each entry says what and where. */
    public List<String> blocked() {
        return Collections.unmodifiableList(new ArrayList<>(blocked));
    }

    /** World-changing calls found (names only). */
    public List<String> mutators() {
        return Collections.unmodifiableList(new ArrayList<>(mutators));
    }

    @Override
    public void call(SourceUnit source, GeneratorContext context, ClassNode classNode) {
        Visitor visitor = new Visitor(source);
        for (MethodNode method : classNode.getMethods()) {
            Statement code = method.getCode();
            if (code == null || method.isAbstract()) {
                continue;
            }
            code.visit(visitor);
            method.setCode(withCheck(code));
        }
        // Field initializers and the like are visited for footguns too; they run once and need no checks.
        visitor.visitClass(classNode);
    }

    static Statement checkStatement() {
        return new ExpressionStatement(
            new StaticMethodCallExpression(
                ClassHelper.make(Deadline.class),
                "check",
                ArgumentListExpression.EMPTY_ARGUMENTS));
    }

    static Statement withCheck(Statement code) {
        if (code instanceof BlockStatement) {
            BlockStatement block = (BlockStatement) code;
            List<Statement> statements = block.getStatements();
            if (!statements.isEmpty() && isCheck(statements.get(0))) {
                return block;
            }
            statements.add(0, checkStatement());
            return block;
        }
        BlockStatement block = new BlockStatement();
        block.setVariableScope(new VariableScope());
        block.addStatement(checkStatement());
        if (code != null) {
            block.addStatement(code);
        }
        return block;
    }

    private static boolean isCheck(Statement s) {
        if (!(s instanceof ExpressionStatement)) {
            return false;
        }
        Expression e = ((ExpressionStatement) s).getExpression();
        return e instanceof StaticMethodCallExpression && "check".equals(((StaticMethodCallExpression) e).getMethod())
            && ((StaticMethodCallExpression) e).getOwnerType()
                .getName()
                .equals(Deadline.class.getName());
    }

    private final class Visitor extends ClassCodeVisitorSupport {

        private final SourceUnit source;

        Visitor(SourceUnit source) {
            this.source = source;
        }

        @Override
        protected SourceUnit getSourceUnit() {
            return source;
        }

        @Override
        public void visitForLoop(ForStatement loop) {
            super.visitForLoop(loop);
            loop.setLoopBlock(withCheck(loop.getLoopBlock()));
        }

        @Override
        public void visitWhileLoop(WhileStatement loop) {
            super.visitWhileLoop(loop);
            loop.setLoopBlock(withCheck(loop.getLoopBlock()));
        }

        @Override
        public void visitDoWhileLoop(DoWhileStatement loop) {
            super.visitDoWhileLoop(loop);
            loop.setLoopBlock(withCheck(loop.getLoopBlock()));
        }

        @Override
        public void visitClosureExpression(ClosureExpression closure) {
            super.visitClosureExpression(closure);
            closure.setCode(withCheck(closure.getCode()));
        }

        @Override
        public void visitMethodCallExpression(MethodCallExpression call) {
            super.visitMethodCallExpression(call);
            String name = call.getMethodAsString();
            if (name == null) {
                return;
            }
            if (BLOCKED.contains(name) && !harmlessStop(call, name)) {
                blocked.add(name + "() at line " + call.getLineNumber());
            }
            if (MUTATORS.contains(name)) {
                mutators.add(name);
            }
            if (COMMAND_CALLS.contains(name)) {
                for (Expression arg : arguments(call.getArguments())) {
                    if (arg instanceof ConstantExpression && ((ConstantExpression) arg).getValue() instanceof String
                        && STOP_COMMAND.matcher((String) ((ConstantExpression) arg).getValue())
                            .matches()) {
                        blocked.add("a server stop command at line " + call.getLineNumber());
                    }
                }
            }
        }

        @Override
        public void visitStaticMethodCallExpression(StaticMethodCallExpression call) {
            super.visitStaticMethodCallExpression(call);
            String name = call.getMethod();
            if (BLOCKED.contains(name) && !"check".equals(name)) {
                blocked.add(name + "() at line " + call.getLineNumber());
            }
            if (MUTATORS.contains(name)) {
                mutators.add(name);
            }
        }

        @Override
        public void visitBinaryExpression(BinaryExpression expr) {
            super.visitBinaryExpression(expr);
            String op = expr.getOperation()
                .getText();
            if (op.endsWith("=") && !"==".equals(op)
                && !"!=".equals(op)
                && !"<=".equals(op)
                && !">=".equals(op)
                && !"===".equals(op)
                && !"!==".equals(op)
                && expr.getLeftExpression() instanceof PropertyExpression) {
                String prop = ((PropertyExpression) expr.getLeftExpression()).getPropertyAsString();
                if (prop != null && MUTATOR_PROPERTIES.contains(prop)) {
                    mutators.add(prop + " =");
                }
            }
        }

        /** {@code stop} is blocked only as a no-argument call or on a server/thread; {@code list.stop(x)} is fine. */
        private boolean harmlessStop(MethodCallExpression call, String name) {
            if (!"stop".equals(name) && !"suspend".equals(name)) {
                return false;
            }
            String receiver = call.getObjectExpression()
                .getText()
                .toLowerCase(Locale.ROOT);
            return !(receiver.contains("server") || receiver.contains("thread"));
        }

        private List<Expression> arguments(Expression args) {
            if (args instanceof TupleExpression) {
                return ((TupleExpression) args).getExpressions();
            }
            return Collections.singletonList(args);
        }
    }
}
