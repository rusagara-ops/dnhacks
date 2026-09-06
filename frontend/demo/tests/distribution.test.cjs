const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../distribution.js'), 'utf8'), context);
const view = context.window.WorkDistribution;
test('groups accepted work by worker ID and keeps unassigned failures unattributed', () => {
  const rows = view.summarize([
    {worker_id:'a',worker_name:'Mac',status:'COMPLETED',input_count:2,execution_time_ms:200},
    {worker_id:'a',worker_name:'Mac',status:'COMPLETED',input_count:1,execution_time_ms:100},
    {worker_id:'b',worker_name:'Mac',status:'RUNNING',input_count:1},
    {worker_id:null,status:'FAILED',input_count:1},
  ], [{id:'c',name:'Idle',status:'AVAILABLE'},{id:'old',name:'Offline',status:'OFFLINE'}]);
  const a=rows.find(r=>r.id==='a');assert.equal(a.completed,2);assert.equal(a.inputs,3);assert.equal(a.milliseconds,300);assert.equal(a.timed,2);
  assert.equal(rows.find(r=>r.id==='b').active,1);assert.equal(rows.find(r=>r.id===null).failed,1);
  assert.equal(rows.find(r=>r.id==='c').completed,0);assert.equal(rows.some(r=>r.id==='old'),false);
});
test('compatibility uses the selected model inventory and exact revision',()=>{
  const w={model_id:'gemma',status:'AVAILABLE',models:[{model_id:'qwen',model_revision:'v1',supported_tasks:['coding-assistance']}]};
  const j={model_id:'qwen',model_revision:'v1',task_type:'coding-assistance'};
  assert.equal(view.compatibility(w,j),'Compatible');
  assert.equal(view.compatibility(w,{...j,model_revision:'v2'}),'Model / revision mismatch');
  assert.equal(view.compatibility(w,{...j,task_type:'summarization'}),'Task unsupported');
});
test('heartbeat-only refresh preserves the DOM and expanded task details', () => {
  class Element {
    constructor(tag) { this.tag=tag; this.children=[]; this.dataset={}; }
    append(...children) { this.children.push(...children); }
    replaceChildren() { this.children=[]; }
    setAttribute() {}
    get childElementCount() { return this.children.length; }
    querySelector(tag) { for (const child of this.children) { if(child.tag===tag) return child; const found=child.querySelector(tag); if(found) return found; } return null; }
  }
  context.document={createElement:tag=>new Element(tag)};
  const container=new Element('div');
  const job={id:'job',total_tasks:1,model_id:'qwen',model_revision:'v1',task_type:'coding-assistance'};
  const worker={id:'a',name:'Mac',status:'AVAILABLE',model_id:'qwen',model_revision:'v1',supported_tasks:['coding-assistance']};
  const result={status:'RUNNING',tasks:[{task_id:'task-123456',worker_id:'a',worker_name:'Mac',status:'RUNNING',input_start_index:0,input_count:1,attempt_count:1}]};
  view.render(container,job,result,[worker]);
  const first=container.children[0], details=container.querySelector('details'); details.open=true;
  view.render(container,job,result,[{...worker,last_heartbeat:'new timestamp',ram_available_gb:7}]);
  assert.equal(container.children[0],first);
  assert.equal(container.querySelector('details'),details);
  view.render(container,job,{...result,status:'COMPLETED',tasks:[{...result.tasks[0],status:'COMPLETED',execution_time_ms:200}]},[worker]);
  assert.notEqual(container.children[0],first);
  assert.equal(container.querySelector('details').open,true);
});
