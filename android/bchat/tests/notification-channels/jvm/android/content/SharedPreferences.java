package android.content;
import java.util.Map;
public interface SharedPreferences {
    Map<String,?> getAll();
    Editor edit();
    interface Editor {Editor putBoolean(String key,boolean value);boolean commit();}
}
