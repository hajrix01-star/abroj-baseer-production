package com.baseer.freshchat;

import org.json.JSONObject;

/** Source for the read-only same-origin media bridge. Uploads use native HTTPS capabilities. */
final class BChatConnectedMediaBridge {
    private BChatConnectedMediaBridge() { }

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
