// Unpack a Pack200 stream to a jar using Apache Commons Compress (Java 14+ removed java.util.jar.Pack200).
// usage: java -cp commons-compress.jar:commons-io.jar:commons-lang3.jar Unpack200.java in.pack out.jar
import java.io.*;
import java.util.jar.JarOutputStream;
import org.apache.commons.compress.java.util.jar.Pack200;

public class Unpack200 {
    public static void main(String[] a) throws Exception {
        try (
JarOutputStream out = new JarOutputStream(new FileOutputStream(a[1]))) {
            Pack200.newUnpacker().unpack(new File(a[0]), out);
        }
    }
}
