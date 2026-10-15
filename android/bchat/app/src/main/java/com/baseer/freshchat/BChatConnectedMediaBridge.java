package com.baseer.freshchat;

import com.baseer.freshchat.sync.BChatConnectedMediaStore;

import org.json.JSONObject;

import java.io.IOException;

/** Source for a single same-origin, back-pressured media upload port. No cookies leave WebView. */
final class BChatConnectedMediaBridge {
    private BChatConnectedMediaBridge() { }

    static String uploadScript(String origin, String bridge, String path, String csrf,
                               BChatConnectedMediaStore.Entry entry, int nonce) throws IOException {
        String metadata = entry.uploadMetadata().toString();
        return "(function(){"
                + "var h=function(e){var p=e.ports&&e.ports[0];"
                + "if(!p||e.data!=='bchat-media-upload')return;"
                + "window.removeEventListener('message',h);"
                + "var path=" + JSONObject.quote(path) + ",u=new URL(path,location.origin);"
                + "if(location.href!==" + JSONObject.quote(bridge)
                + "||location.origin!==" + JSONObject.quote(origin)
                + "||u.origin!==location.origin||u.pathname!==path){p.postMessage('{}');return;}"
                + "var parts=[],count=0,sequence=0,ended=false,expected=" + entry.size + ";"
                + "var controller=new AbortController();window.__bchatMediaAbort=controller;"
                + "function done(status,type,url,body){p.postMessage(JSON.stringify({nonce:" + nonce
                + ",type:'result',status:status,content_type:type,url:url,body:body}));"
                + "if(window.__bchatMediaAbort===controller)window.__bchatMediaAbort=null;}"
                + "p.onmessage=function(event){try{var x=JSON.parse(event.data);"
                + "if(ended||x.nonce!==" + nonce + "||x.seq!==sequence++||typeof x.end!=='boolean')throw Error('sequence');"
                + "if(x.end){if(count!==expected)throw Error('size');ended=true;"
                + "var form=new FormData();form.append('csrf_token'," + JSONObject.quote(csrf) + ");"
                + "form.append('metadata'," + JSONObject.quote(metadata) + ");"
                + "form.append('file',new Blob(parts,{type:" + JSONObject.quote(entry.mime) + "}),"
                + JSONObject.quote(entry.name) + ");parts=[];"
                + "fetch(u.href,{method:'POST',credentials:'same-origin',redirect:'manual',cache:'no-store',"
                + "body:form,signal:controller.signal,headers:{Accept:'application/json'}})"
                + ".then(function(r){if(r.type==='opaqueredirect'){done(401,'application/json',u.href,'{}');return;}"
                + "if(!r.body||!r.body.getReader)throw Error('stream');"
                + "var rd=r.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true}),body='',size=0;"
                + "function read(){return rd.read().then(function(part){if(part.done){body+=decoder.decode();"
                + "done(r.status,r.headers.get('content-type')||'',r.url,body);return;}"
                + "size+=part.value.byteLength;if(size>8192){rd.cancel();throw Error('response size');}"
                + "body+=decoder.decode(part.value,{stream:true});return read();});}return read();})"
                + ".catch(function(){done(0,'',u.href,'{}');});return;}"
                + "if(typeof x.data!=='string'||x.data.length>44000)throw Error('chunk size');"
                + "var raw=atob(x.data);if(raw.length<1||raw.length>32768||count+raw.length>expected)"
                + "throw Error('chunk bound');"
                + "var bytes=new Uint8Array(raw.length);for(var i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);"
                + "parts.push(bytes);count+=raw.length;"
                + "p.postMessage(JSON.stringify({nonce:" + nonce + ",type:'ack',seq:x.seq}));"
                + "}catch(error){controller.abort();done(0,'',u.href,'{}');}};"
                + "p.postMessage(JSON.stringify({nonce:" + nonce + ",type:'ready'}));};"
                + "window.addEventListener('message',h);})();";
    }

    static String readScript(String origin, String bridge, String path, int nonce, int limit) {
        return "(function(){var h=function(e){var p=e.ports&&e.ports[0];"
                + "if(!p||e.data!=='bchat-media-read')return;"
                + "window.removeEventListener('message',h);var path=" + JSONObject.quote(path)
                + ",u=new URL(path,location.origin);"
                + "if(location.href!==" + JSONObject.quote(bridge)
                + "||location.origin!==" + JSONObject.quote(origin)
                + "||u.origin!==location.origin||u.pathname!==path){p.postMessage('{}');return;}"
                + "var controller=new AbortController();window.__bchatMediaReadAbort=controller;"
                + "var reader=null,buffer=null,offset=0,seq=0,total=0,finished=false;"
                + "function message(type,extra){extra=extra||{};extra.nonce=" + nonce
                + ";extra.type=type;p.postMessage(JSON.stringify(extra));}"
                + "function fail(){if(finished)return;finished=true;message('error');}"
                + "function next(){if(finished)return;"
                + "Promise.resolve().then(function(){if(buffer&&offset<buffer.length)return {value:buffer,done:false};"
                + "return reader.read().then(function(part){buffer=part.value||null;offset=0;return part;});})"
                + ".then(function(part){if(part.done){finished=true;message('end',{size:total});return;}"
                + "if(!buffer||offset>=buffer.length)throw Error('empty chunk');"
                + "var n=Math.min(65536,buffer.length-offset),part=buffer.subarray(offset,offset+n);offset+=n;"
                + "total+=n;if(total>" + limit + ")throw Error('size');"
                + "var raw='';for(var i=0;i<part.length;i++)raw+=String.fromCharCode(part[i]);"
                + "message('chunk',{seq:seq++,data:btoa(raw)});}).catch(fail);}"
                + "p.onmessage=function(event){try{var x=JSON.parse(event.data);"
                + "if(x.nonce!==" + nonce + "||x.type!=='next'||x.seq!==seq)throw Error('ack');"
                + "next();}catch(error){controller.abort();fail();}};"
                + "fetch(u.href,{method:'GET',credentials:'same-origin',redirect:'manual',cache:'no-store',"
                + "signal:controller.signal,headers:{Accept:'image/jpeg,image/png,image/webp,application/pdf,audio/mp4,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/plain'}})"
                + ".then(function(r){if(r.type==='opaqueredirect'){finished=true;"
                + "message('start',{status:401,url:u.href,mime:'',length:0});return;}"
                + "var size=Number(r.headers.get('content-length')||0);"
                + "message('start',{status:r.status,url:r.url,mime:r.headers.get('content-type')||'',length:size});"
                + "if(r.status!==200){finished=true;return;}"
                + "if(!r.body||!r.body.getReader)throw Error('stream');reader=r.body.getReader();})"
                + ".catch(fail);};window.addEventListener('message',h);})();";
    }
}
