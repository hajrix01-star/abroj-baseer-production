/** Isolated native layout fixture. Never imported by the application entry point. */
import React, { useEffect, useState } from 'react';
import { NativeModules, Text, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { registerRootComponent } from 'expo';
import * as Crypto from 'expo-crypto';
import * as FS from 'expo-file-system/legacy';
import * as fixtureRuntime from '../src/odoo/runtime';
import { ImageViewer } from '../src/odoo/ui/ImageViewer';
import { translator } from '../src/odoo/ui/dictionary';
import { Button } from '../src/odoo/ui/components';
import { SessionApp } from '../src/odoo/OdooTrialApp';
import {
  ChatEngine,
  ChatError,
  type Bootstrap,
  type Message,
  type Request,
  type Room,
  type Storage,
} from '../src/odoo/core/ChatEngine';

const marker = 'SYNTHETIC_UI_PREVIEW';
let avatarUploads = 0;
const avatarObservers = new Set<() => void>();
const descriptions = new Map<number, string>([
  [11, 'تنسيق المشتريات ومتابعة طلبات الفريق — Purchasing coordination.'],
  [12, 'معلومات المجموعة للأعضاء — Read-only group information.'],
]);
const rooms: Room[] = [
  {
    id: 11,
    company_id: 1,
    membership_id: 21,
    name: 'مجموعة المشتريات — Purchasing',
    is_group: true,
    is_group_admin: true,
    avatar_version: 1,
    last_message_preview: 'تمت مراجعة الطلب، شكرًا لكم',
    unread_count: 2,
  },
  {
    id: 12,
    company_id: 1,
    membership_id: 22,
    name: 'الإدارة — Management',
    is_group: true,
    avatar_version: 0,
    last_message_preview: 'اجتماع فريق العمل',
  },
  {
    id: 13,
    company_id: 2,
    membership_id: 23,
    name: 'المبيعات — Sales',
    is_group: true,
    avatar_version: 0,
    last_message_preview: 'Sales team',
  },
];
const identity: Bootstrap = {
  api_version: 2,
  database: 'synthetic',
  user_id: 7,
  company_ids: [1, 2],
  current_company_id: 1,
  csrf_token: 'synthetic-not-a-credential',
  permissions: { chat_view: true, chat_send: true, media: true, group_create: true, revision: 1 },
  mobile_policy: [
    { api_version: 2, company_id: 1, direct_enabled: true, can_manage: true },
    { api_version: 2, company_id: 2, direct_enabled: false, can_manage: false },
  ],
  profile: {
    name: 'حساب معاينة — Preview User',
    companies: [
      {
        id: 1,
        name: 'Preview One',
        name_ar: 'شركة المعاينة الأولى للمطاعم والخدمات التجارية',
        name_en: 'First Preview Restaurant and Commercial Services Company',
      },
      {
        id: 2,
        name: 'Preview Two',
        name_ar: 'شركة المعاينة الثانية',
        name_en: 'Second Preview Company',
      },
    ],
  },
};
const messages: Message[] = Array.from({ length: 16 }, (_, i) => ({
  id: i + 1,
  author_user_id: i % 2 ? 7 : 8,
  author_name: i % 2 ? 'Preview User' : 'فريق المشتريات',
  text: [
    'مرحبًا، هذا مثال لمحادثة مجموعة المشتريات.',
    'تمت مراجعة الطلب، شكرًا لكم.',
    'A longer English message to check wrapping and the message bubble width on a narrow screen.',
    'نص عربي أطول لاختبار التفاف الرسالة ومساحة القراءة داخل المحادثة دون خروج المحتوى عن عرض الشاشة.',
  ][i % 4]!,
  created_at: `2026-10-18 12:${String(i).padStart(2, '0')}:00`,
  delivery_state: i % 2 ? 'read' : 'sent',
}));
class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  async getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  async setItem(key: string, value: string) {
    this.data.set(key, value);
  }
  async removeItem(key: string) {
    this.data.delete(key);
  }
  async getAllKeys() {
    return [...this.data.keys()];
  }
}
const transport = {
  async request(r: Request): Promise<unknown> {
    if (r.path === '/web/session/destroy') return { result: null };
    if (r.path === '/web/session/authenticate') return { result: { uid: 7, db: 'synthetic' } };
    if (r.path === '/bchat/api/v2/bootstrap') return identity;
    if (r.path === '/bchat/api/v2/rooms' && r.method === 'GET') return { api_version: 2, rooms };
    if (r.path.startsWith('/bchat/api/v2/changes'))
      return { api_version: 2, changes: [], next_after: 0, watermark: 0, reset_required: false };
    if (r.path.startsWith('/bchat/api/v2/mobile/candidates')) {
      const query = decodeURIComponent(r.path.split('&q=')[1] || '').toLowerCase();
      return { api_version: 2, users: [{user_id: 8, name: 'مدير المجموعة — Group administrator'},
        {user_id: 9, name: 'عضو فريق العمل — Team member'},
        {user_id: 10, name: 'موظف مرشح — Candidate employee'}].filter(user => user.name.toLowerCase().includes(query)) };
    }
    const group = /^\/bchat\/api\/v2\/rooms\/(\d+)\/group$/.exec(r.path);
    if (group) {
      const room = rooms.find(row => row.id === Number(group[1]));
      if (!room) throw new ChatError('room_unavailable');
      if (r.method === 'POST') {
        const payload = JSON.parse(r.form!.payload!);
        if (payload.action === 'rename') room.name = payload.name;
        if (payload.action === 'set_description') descriptions.set(room.id, payload.description);
        return { api_version: 2, room_id: room.id, action: payload.action };
      }
      return { api_version: 2, room: { id: room.id, company_id: room.company_id, name: room.name,
        description: descriptions.get(room.id) ?? '', avatar_version: room.avatar_version ?? 0,
        is_group: true }, can_manage: room.id === 11,
        members: [{user_id: 7, name: identity.profile!.name, is_admin: true},
          {user_id: 8, name: 'مدير المجموعة — Group administrator', is_admin: true},
          {user_id: 9, name: 'عضو فريق العمل — Team member', is_admin: false}] };
    }
    const receipt = /messages\/(\d+)\/receipts$/.exec(r.path);
    if (receipt)
      return {
        api_version: 2,
        message_id: Number(receipt[1]),
        delivered_at: '2026-10-18 12:30:00',
        read_at: '2026-10-18 12:30:01',
        unread_count: 0,
        last_message_id: 16,
        replayed: false,
      };
    if (/\/rooms\/\d+\/messages/.test(r.path) && r.method === 'GET')
      return { api_version: 2, messages, next_before_id: null };
    if (/\/rooms\/\d+\/messages$/.test(r.path) && r.method === 'POST') {
      // Local deterministic latency exercises a responsive composer before remote ACK.
      await new Promise(resolve => setTimeout(resolve, 1500));
      const payload = JSON.parse(r.form!.payload!);
      const id = messages.length + 1;
      const parent = messages.find(message => message.id === payload.reply_to_message_id);
      messages.push({
        id,
        author_user_id: 7,
        author_name: 'Preview User',
        text: payload.text,
        created_at: '2026-10-18 12:31:00',
        delivery_state: 'sent',
        ...(parent ? { reply: { id: parent.id, author_name: parent.author_name, text: parent.text } } : {}),
      });
      return {
        api_version: 2,
        room_id: 11,
        membership_id: 21,
        client_uuid: payload.client_uuid,
        message_id: id,
        state: 'sent',
      };
    }
    throw new ChatError('preview_route_not_supported');
  },
};
const engine = new ChatEngine({
  uuid: Crypto.randomUUID,
  storage: new MemoryStorage(),
  transport,
  origin: 'https://ui-preview.invalid',
  database: 'synthetic',
  uploadGroupAvatar: async room => {
    avatarUploads++;
    const current = rooms.find(row => row.id === room.id)!;
    current.avatar_version = (current.avatar_version ?? 0) + 1;
    for (const notify of avatarObservers) notify();
    return {api_version:2,room_id:room.id,avatar_version:current.avatar_version};
  },
});
function PreviewApp() {
  const [, updateAvatarProbe] = useState(0);
  const [ready, setReady] = useState(false);
  const [surface, setSurface] = useState<'choose' | 'chat' | 'image' | 'feedback'>('choose');
  const [feedback, setFeedback] = useState('Not checked');
  const [imageUri, setImageUri] = useState('');
  const [imageLanguage, setImageLanguage] = useState<'ar' | 'en'>('ar');
  useEffect(() => {
    const notifyAvatar = () => updateAvatarProbe(value => value + 1);
    avatarObservers.add(notifyAvatar);
    void engine.login('synthetic', 'synthetic', true).then(() => setReady(true));
    // Android drawable resource names are not file:// URLs. Keep the production
    // viewer's file-only guard and create a small local geometric fixture instead.
    const uri = `${FS.cacheDirectory}cw36-local-image.png`;
    const png = 'iVBORw0KGgoAAAANSUhEUgAAAHgAAABQCAIAAABd+SbeAAAAzElEQVR4nO3QUQmAAABEMZP4bU4jmsQIxngnDJZgx3k/v/Pe1+8c+ZroXfma6F2iRYvO5Wuid4kWLTqXr4neJVq06Fy+JnqXaNGic/ma6F2iRYvO5Wuid4kWLTqXr4neJVq06Fy+JnqXaNGic/ma6F2iRYvO5Wuid4kWLTqXr4neJVq06Fy+JnqXaNGic/ma6F2iRYvO5Wuid4kWLTqXr4neJVq06Fy+JnqXaNGic/ma6F2iRYvO5Wuid4kWLTqXr4neJVq06Fy+JnrXB2/sJFi/ek+mAAAAAElFTkSuQmCC';
    void FS.writeAsStringAsync(uri, png, { encoding: FS.EncodingType.Base64 }).then(() => {
      // Fixture-only native seam: actual Timeline/MediaTile/FlashList, synthetic local
      // resolution instead of a real Odoo account. Never imported by normal entry.
      Object.assign(fixtureRuntime, {
        // Synthetic UI-only seam. Runtime authorization/cache/upload tests use production code separately.
        readGroupAvatar: async (_current:ChatEngine, room:Room) => ({
          uri:`data:image/png;base64,${png}`,version:room.avatar_version ?? 0,
          key:`SYNTHETIC_UI_PREVIEW/${room.company_id}/${room.id}/${room.membership_id}/${room.avatar_version}`,
        }),
        hasGroupAvatar: (key:string) => key.startsWith('SYNTHETIC_UI_PREVIEW/'),
        localMedia: async () => {
        await new Promise(resolve => setTimeout(resolve, 250));
        return uri;
      } });
      messages[15]!.media = { id: 37, kind: 'image', mime: 'image/png', size: 261,
        sha256: 'a'.repeat(64), name: 'CW37 inline preview.png' };
      setImageUri(uri);
    });
    return () => { avatarObservers.delete(notifyAvatar); };
  }, []);
  if (surface === 'feedback') return (
    <SafeAreaProvider><SafeAreaView style={{flex:1,padding:20,gap:16,backgroundColor:'white'}}>
      <Text>FF native tone acceptance (not an audible recording)</Text>
      <Text accessibilityLabel="FF feedback result">{feedback}</Text>
      {(['send','receive'] as const).map(kind => <Button key={kind} title={`FF ${kind} tone`}
        onPress={() => { void NativeModules.BWorkFeedback.play(kind).then((accepted:boolean) =>
          setFeedback(`${kind}: ${accepted ? 'accepted' : 'suppressed'}`)); }} />)}
      <Button title="FF stop tone" onPress={() => NativeModules.BWorkFeedback.stop()} />
      <Button title="FF back" onPress={() => setSurface('choose')} />
    </SafeAreaView></SafeAreaProvider>
  );
  return (
    <SafeAreaProvider>
      {!ready ? <Text>{marker}</Text> : surface === 'chat' ? (
        <View collapsable={false} testID={`FF-avatar-upload-${avatarUploads}-version-${rooms[0]?.avatar_version ?? 0}`}
          style={{flex:1}}><SessionApp engine={engine} /></View>
      ) : surface === 'image' ? (
        <ImageViewer uri={imageUri} name="CW36 local test image" language={imageLanguage} t={translator(imageLanguage)}
          onClose={() => setSurface('choose')} />
      ) : (
        <SafeAreaView style={{ flex: 1, padding: 24, justifyContent: 'center' }}>
          <View style={{ gap: 20 }}>
            <Text>{marker}</Text>
            <Button title="CW36 chat check" onPress={() => setSurface('chat')} />
            <Button title="FF native feedback check" onPress={() => setSurface('feedback')} />
            <Button title="CW36 image check" disabled={!imageUri} onPress={() => { setImageLanguage('ar'); setSurface('image'); }} />
            <Button title="CW36 image English" disabled={!imageUri} onPress={() => { setImageLanguage('en'); setSurface('image'); }} />
          </View>
        </SafeAreaView>
      )}
    </SafeAreaProvider>
  );
}
registerRootComponent(PreviewApp);
