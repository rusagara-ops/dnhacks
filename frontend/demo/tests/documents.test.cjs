const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const context={window:{},TextEncoder,TextDecoder};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../documents.js'),'utf8'),context);
const docs=context.window.Documents;
test('batch preserves full documents and validates each UTF-8 size',()=>{
  assert.deepEqual(Array.from(docs.validate([{name:'a.txt',text:'a\n\nb'},{name:'b.txt',text:'😀'}])),['a\n\nb','😀']);
  assert.throws(()=>docs.validate([{name:'long.txt',text:'😀'.repeat(1501)}]),/long.txt/);
  assert.throws(()=>docs.validate([{name:'bad.pdf',error:'Scanned',text:null}]),/Scanned/);
  assert.throws(()=>docs.validate([{name:'a',text:'a'.repeat(6000)}],'b'.repeat(501)),/6,500/);
  assert.throws(()=>docs.validate([{name:'empty',text:'  '}]),/no readable text/);
});
test('TXT parsing rejects unsupported, empty, binary and oversized files',async()=>{
 const file=(name,text)=>({name,size:Buffer.byteLength(text),arrayBuffer:async()=>new TextEncoder().encode(text).buffer});
 assert.equal(await docs.parse(file('a.txt','alpha\n\nbeta')),'alpha\n\nbeta');
 await assert.rejects(docs.parse(file('a.docx','test')),/Supported/);
 await assert.rejects(docs.parse(file('a.txt','')),/empty/);
 await assert.rejects(docs.parse(file('a.txt','\0binary')),/binary/);
 await assert.rejects(docs.parse({name:'a.pdf',size:11*1024*1024}),/10 MiB/);
});
