// Empty component required for the SMS role (the helper never receives or sends messages).
package pl.admenot.helper;
public class RespondService extends android.app.Service {
    @Override public android.os.IBinder onBind(android.content.Intent i) { return null; }
}
