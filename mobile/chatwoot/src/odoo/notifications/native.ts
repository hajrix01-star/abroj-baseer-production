import { NativeModules } from 'react-native';
import type { NativePush } from './NotificationsEngine';
const module = () => NativeModules?.BWorkNotifications;
export const nativePush: NativePush = {
  async status() { return module() ? module().status() : {configured:false,enabled:false,granted:false}; },
  async enable() { return module() ? module().enable() : false; },
  async disable() { if(module()) { module().clearNow(); await module().disable(); } },
  async clear() { if(module() && !module().clearNow())throw new Error('push_unavailable'); },
  async token() { return module() ? module().token() : null; },
  async bind(scope,installation,token,key,epoch) { return module() ? module().bind(scope,installation,token,key,epoch??-1) : false; },
};
