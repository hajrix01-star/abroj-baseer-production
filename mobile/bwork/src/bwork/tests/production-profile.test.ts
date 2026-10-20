import assert from 'node:assert/strict';
import { test } from 'node:test';
import { applicationRealm, compatibility, configurationAlias } from '../compatibility.ts';

test('runtime production realm rejects QA private and altered public origins or databases before any transport exists', () => {
  const valid = { profile: 'production', origin: compatibility.production.origin, database: compatibility.production.database };
  assert.deepEqual(applicationRealm(valid), valid);
  assert.equal(Object.isFrozen(applicationRealm(valid)), true);
  for (const origin of ['https://baseer-live-qa.tail938958.ts.net', 'https://localhost', 'https://127.0.0.1', 'https://10.0.0.1', 'https://192.168.1.1', 'https://[::1]', 'http://baseer.abroj.sa', 'https://baseer.abroj.sa/', 'https://baseer.abroj.sa:444', 'https://baseer.abroj.sa/path', 'https://baseer.abroj.sa.evil.test']) assert.throws(() => applicationRealm({ ...valid, origin }));
  for (const database of ['', 'baseer_live_qa_clean_20260928', 'baseer_prod_copy', ' baseer_prod', 'baseer_prod ']) assert.throws(() => applicationRealm({ ...valid, database }));
  assert.throws(() => applicationRealm({ ...valid, profile: 'prod' }));
});

test('runtime QA aliases stay compatible and conflicting aliases still fail without mixing production identity', () => {
  const input = { profile: 'qa', origin: configurationAlias(undefined, 'https://qa.example.test'), database: configurationAlias(undefined, 'synthetic_qa') };
  assert.deepEqual(applicationRealm(input), input);
  assert.equal(applicationRealm({ profile: 'qa', origin: '', database: '' }).profile, 'qa');
  assert.throws(() => configurationAlias('https://baseer.abroj.sa', 'https://qa.example.test'));
  assert.notEqual(compatibility.qa.applicationId, compatibility.production.applicationId);
  assert.equal(compatibility.production.origin, 'https://baseer.abroj.sa');
  assert.equal(compatibility.production.database, 'baseer_prod');
});
