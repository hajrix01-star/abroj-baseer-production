package com.baseer.bwork.notifications;
import com.facebook.react.ReactPackage;
import com.facebook.react.bridge.NativeModule;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.uimanager.ViewManager;
import java.util.Collections;
import java.util.List;
public final class BWorkNotificationsPackage implements ReactPackage {
  public List<NativeModule> createNativeModules(ReactApplicationContext c){return Collections.singletonList(new BWorkNotificationsModule(c));}
  public List<ViewManager> createViewManagers(ReactApplicationContext c){return Collections.emptyList();}
}
