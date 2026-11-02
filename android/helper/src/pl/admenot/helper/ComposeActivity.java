// Empty component required for the SMS role (the helper never receives or sends messages).
package pl.admenot.helper;
public class ComposeActivity extends android.app.Activity {
    @Override protected void onCreate(android.os.Bundle b) { super.onCreate(b); finish(); }
}
