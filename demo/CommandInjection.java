import java.io.IOException;

public class CommandInjection {
    // VULN: user-controlled input concatenated into a shell command -> command injection
    public static Process listDir(String filename) throws IOException {
        return Runtime.getRuntime().exec("sh -c ls " + filename);
    }

    public static void main(String[] args) throws IOException {
        listDir(args.length > 0 ? args[0] : ".");
    }
}
