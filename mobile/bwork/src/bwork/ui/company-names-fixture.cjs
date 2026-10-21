/** Execute the real pure presentation helpers in host-only component harnesses. */
const ts = require('typescript'), vm = require('node:vm');
const { readFileSync } = require('node:fs'), { join } = require('node:path');
const output = { exports: {} };
vm.runInNewContext(ts.transpileModule(readFileSync(join(__dirname, 'companyNames.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { module: output, exports: output.exports, require() { throw new Error('Company names must stay platform independent'); } });
module.exports = output.exports;
