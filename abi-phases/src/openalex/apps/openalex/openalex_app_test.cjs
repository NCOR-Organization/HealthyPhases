const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');
const html = readFileSync(join(__dirname,'index.html'),'utf8');
function app() {
  function element() { return {value:'',checked:false,children:[],textContent:'',innerHTML:'',disabled:false,append(c){this.children.push(c);},replaceChildren(){this.children=[];},addEventListener(){},get lastElementChild(){return this.lastChild ||= element();}}; }
  const nodes = new Map(), $ = id => {if(!nodes.has(id)) nodes.set(id,element());return nodes.get(id);};
  const context = vm.createContext({document:{getElementById:$,createElement:element},window:{},setInterval(){},fetch:()=>new Promise(()=>{})});
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
  return {context,$};
}
const response = payload => ({status:200,ok:true,text:async()=>JSON.stringify(payload)});
test('queues all saved query records without any preview limit',async()=>{
  const {context,$}=app(); $('query').value='selected'; $('force').checked=true; let sent;
  context.fetch=async(url,options)=>{if(options.method==='POST'){sent=JSON.parse(options.body);return response({total:12345});}return response({requests:[]});};
  await context.submit(); assert.deepEqual(sent,{query_id:'selected',force_refresh:true}); assert.match($('message').textContent,/12345/);
});
test('renders escaped errors and resume only for interrupted requests',async()=>{
  const {context,$}=app();context.fetch=async()=>response({requests:[{request_id:'r',query:'<img src=x>',status:'failed',error:'<script>x</script>',processed:1,total:10},{request_id:'s',query:'ok',status:'succeeded',processed:10,total:10}]});
  await context.requests(); const [failed,done]=$('requests').children; assert.match(failed.innerHTML,/&lt;img/);assert.match(failed.innerHTML,/&lt;script/);assert.equal(failed.lastElementChild.children[0].textContent,'Resume');assert.equal(done.lastElementChild.children.length,0);
});
test('an older status request cannot replace newer progress',async()=>{
 const {context,$}=app();let resolve;context.fetch=()=>new Promise(r=>{resolve=r;});const old=context.requests();context.fetch=async()=>response({requests:[{request_id:'a',query:'new',status:'succeeded'}]});await context.requests();resolve(response({requests:[]}));await old;assert.match($('requests').children[0].innerHTML,/new/);
});
