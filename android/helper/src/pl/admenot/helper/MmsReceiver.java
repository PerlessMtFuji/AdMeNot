// Empty component required for the SMS role (the helper never receives or sends messages).
package pl.admenot.helper;
public class MmsReceiver extends android.content.BroadcastReceiver {
    @Override public void onReceive(android.content.Context c, android.content.Intent i) { }
}
