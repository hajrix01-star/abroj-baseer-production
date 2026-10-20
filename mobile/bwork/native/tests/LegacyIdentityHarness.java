import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.zip.GZIPInputStream;

/** Original v1/v2 producer bytes, actual bounded production reader; no device/data access. */
public final class LegacyIdentityHarness {
  private static Object decode(byte[] bytes) throws Exception {
    Class<?> gate=Class.forName("com.baseer.bwork.legacy.LegacyPreflight");
    Method validate=gate.getDeclaredMethod("validate",byte[].class);validate.setAccessible(true);validate.invoke(null,(Object)bytes);
    Constructor<?> ctor=Class.forName("com.baseer.bwork.legacy.ChatStore$SafeObjectInputStream").getDeclaredConstructor(InputStream.class);ctor.setAccessible(true);
    try(ObjectInputStream in=(ObjectInputStream)ctor.newInstance(new ByteArrayInputStream(bytes))){Object state=in.readObject();if(in.read()!=-1)throw new AssertionError("trailing bytes");return state;}
  }
  public static void main(String[] args) throws Exception {
    for(String name:new String[]{"LEGACY_V1_GZIP_BASE64","LEGACY_V2_GZIP_BASE64"}){
      Field field=ChatStoreTest.class.getDeclaredField(name);field.setAccessible(true);
      byte[] bytes;
      try(GZIPInputStream in=new GZIPInputStream(new ByteArrayInputStream(Base64.getDecoder().decode((String)field.get(null))))){bytes=in.readAllBytes();}
      byte[] before=bytes.clone();Object state=decode(bytes);
      if(!state.getClass().getName().equals("com.baseer.bwork.legacy.ChatStore$State"))throw new AssertionError("wrong canonical state");
      int populated=0;for(Field value:state.getClass().getDeclaredFields()){value.setAccessible(true);Object data=value.get(state);if(data instanceof Map&&!((Map<?,?>)data).isEmpty())populated++;}
      if(populated<3)throw new AssertionError("lost original messages/drafts/identities");
      ByteArrayOutputStream output=new ByteArrayOutputStream();try(ObjectOutputStream out=new ObjectOutputStream(output)){out.writeObject(state);}
      decode(output.toByteArray());
      if(!Arrays.equals(before,bytes))throw new AssertionError("historical source rewritten");
    }
    System.out.println("PASS original v1/v2 producer -> canonical bounded reader -> canonical restart reader; source bytes unchanged");
  }
}
