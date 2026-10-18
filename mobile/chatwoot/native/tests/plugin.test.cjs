const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../with-odoo-trial-native.js'), 'utf8');
const moduleValue = { exports: null };
vm.runInNewContext(source, { module: moduleValue, URL, __dirname: path.join(__dirname, '../..'), require: name => name === '@expo/config-plugins' ? {} : require(name) });
const patch = moduleValue.exports.patchApplication;
const template = 'override fun onCreate() {\n    super.onCreate()\n    loadReactNative(this)\n  }';
test('persistent native session factory registers once before ReactNative and refreshes fixed origin', () => {
  const updated = patch(template, 'https://qa.example.test/');
  assert.ok(updated.indexOf('BaseerSessionNetworking.install("https://qa.example.test")') < updated.indexOf('loadReactNative(this)'));
  assert.equal(patch(updated, 'https://qa.example.test/'), updated);
  assert.equal(patch(updated.replace(/\n/g, '\r\n'), 'https://qa.example.test/'), updated);
  assert.ok(patch(updated, 'https://other.example.test:444').includes('"https://other.example.test:444"'));
});
test('factory generation fails closed on template drift or non-origin configuration', () => {
  for (const origin of ['http://qa.example.test', 'https://user:secret@qa.example.test', 'https://qa.example.test/path', 'https://qa.example.test/?a=1']) assert.throws(() => patch(template, origin));
  assert.throws(() => patch('unknown', 'https://qa.example.test'), /template changed/);
  assert.throws(() => patch(template + '\nloadReactNative(this)', 'https://qa.example.test'), /template changed/);
});
test('foreground feedback package registers once without touching session setup or linker exclusions', () => {
  const input = 'PackageList(this).packages.apply {\n}\n' + template;
  const updated = moduleValue.exports.patchFeedback(patch(input, 'https://qa.example.test'));
  assert.equal((updated.match(/add\(com.baseer.bchat.trial.feedback.BWorkFeedbackPackage\(\)\)/g) || []).length, 1);
  assert.equal(moduleValue.exports.patchFeedback(updated), updated);
  assert.match(updated, /BaseerSessionNetworking.install/);
  assert.throws(() => moduleValue.exports.patchFeedback('drift'), /template changed/);
  assert.match(source, /'FeedbackController.java', 'BWorkFeedbackModule.java', 'BWorkFeedbackPackage.java'/);
  assert.match(source, /'@react-native-firebase\/app', '@react-native-firebase\/messaging'/);
});
