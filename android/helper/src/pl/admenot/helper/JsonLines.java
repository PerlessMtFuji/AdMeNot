package pl.admenot.helper;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStreamReader;

/** Helper input: header line {"kind": ..., "v": 1}, then one JSON record per line. */
final class JsonLines implements AutoCloseable {
    final File dir;
    final String kind;
    private final BufferedReader in;

    JsonLines(File file) throws IOException, JSONException {
        dir = file.getAbsoluteFile().getParentFile();
        in = new BufferedReader(new InputStreamReader(new FileInputStream(file), "UTF-8"));
        String head = in.readLine();
        if (head == null) throw new IOException("empty input");
        JSONObject h = new JSONObject(head);
        if (h.optInt("v", 0) != 1) throw new IOException("unsupported version");
        kind = h.getString("kind");
    }

    /** Next record, or null at the end. Lines that are not JSON come back as an object without "id". */
    JSONObject next() throws IOException {
        String line;
        do {
            line = in.readLine();
            if (line == null) return null;
        } while (line.trim().isEmpty());
        try {
            return new JSONObject(line);
        } catch (JSONException e) {
            return new JSONObject();
        }
    }

    /** A part file named in the input; only plain names next to the input file are accepted. */
    File part(String name) throws IOException {
        if (name.isEmpty() || name.contains("/") || name.contains("\\") || name.equals("..") || name.equals("."))
            throw new IOException("bad part name");
        return new File(dir, name);
    }

    @Override public void close() {
        try { in.close(); } catch (IOException ignored) { }
    }
}
