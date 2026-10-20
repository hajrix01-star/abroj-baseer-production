const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const contract=require('./sdk-contract.json');
function artifact(key){
  const item=contract.artifacts[key];if(!item)throw Error('Unknown BWork native SDK coordinate');
  const root=path.join(process.env.GRADLE_USER_HOME||path.join(os.homedir(),'.gradle'),'caches/modules-2/files-2.1',item.group,item.name,item.version);
  if(!fs.existsSync(root))throw Error('Required pinned SDK missing; run native/sdk-resolver prepareNativeProof: '+key);
  for(const hash of fs.readdirSync(root)){
    const file=path.join(root,hash,item.file);
    if(fs.existsSync(file)){
      if(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==item.sha256)throw Error('BWork native SDK checksum mismatch: '+key);
      return file;
    }
  }
  throw Error('Required pinned SDK artifact missing: '+key);
}
module.exports={contract,artifact};
